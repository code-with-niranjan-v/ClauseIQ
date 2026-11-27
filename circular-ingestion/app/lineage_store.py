"""PostgreSQL storage for circular lineage, rebuilt from the stored circular chunks."""
import logging
from collections import defaultdict

import psycopg

from app import lineage
from app.embeddings import Embedder

logger = logging.getLogger(__name__)


class LinkNotFound(LookupError):
    pass


class LinkAlreadyDecided(RuntimeError):
    pass


class LineageStore:
    def __init__(self, database_url: str, graph=None) -> None:
        self._url = database_url
        self._graph = graph

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._url, connect_timeout=10)

    def _pages(self, connection) -> dict[str, list[tuple[int, str]]]:
        """Each circular's pages, rebuilt from its chunks in offset order."""
        pages: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
        for document_id, page_number, content in connection.execute(
                """
                SELECT k.document_id, k.page_number, k.content FROM document_chunk k
                JOIN regulatory_document_version v ON v.id = k.document_version_id
                WHERE k.document_type = 'CIRCULAR' AND v.processing_status = 'COMPLETED'
                ORDER BY k.document_id, k.page_number, k.start_offset
                """):
            pages[document_id][page_number or 0].append(content)
        return {document_id: [(number, "\n".join(parts)) for number, parts in sorted(by_page.items())]
                for document_id, by_page in pages.items()}

    def refresh(self) -> dict:
        """Re-detect every circular's reference numbers and citations. Decided links keep their decision."""
        with self._connect() as connection, connection.cursor() as cursor:
            titles = dict(cursor.execute("SELECT id, title FROM regulatory_document").fetchall())
            pages = self._pages(connection)
            owners: dict[str, str] = {}
            own_by_document: dict[str, set[str]] = {}
            cursor.execute("DELETE FROM document_identifier")
            for document_id, document_pages in pages.items():
                own = lineage.own_identifiers(document_pages, titles.get(document_id, ""))
                own_by_document[document_id] = own
                rows = {lineage.normalize(item): item for item in own}
                cursor.executemany(
                    "INSERT INTO document_identifier (document_id, identifier, normalized) VALUES (%s, %s, %s)",
                    [(document_id, printed, normalized) for normalized, printed in rows.items()])
                for normalized in rows:
                    owners.setdefault(normalized, document_id)

            proposed = 0
            for document_id, document_pages in pages.items():
                detected = []
                for citation in lineage.detect(document_pages, own_by_document[document_id]):
                    target = owners.get(citation.normalized)
                    if target == document_id or (citation.relation == "REFERS_TO" and target is None):
                        continue   # unresolved plain references are noise
                    detected.append((citation, target))
                keys = [citation.normalized for citation, _ in detected]
                cursor.execute(
                    """
                    DELETE FROM circular_link WHERE source_document_id = %s AND status = 'PROPOSED'
                      AND NOT (cited_normalized = ANY(%s))
                    """, (document_id, keys))
                for citation, target in detected:
                    cursor.execute(
                        """
                        INSERT INTO circular_link (id, source_document_id, relation, cited_identifier, cited_normalized,
                                                   target_document_id, page_number, evidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_document_id, cited_normalized) DO UPDATE
                            SET relation = EXCLUDED.relation, cited_identifier = EXCLUDED.cited_identifier,
                                target_document_id = EXCLUDED.target_document_id, page_number = EXCLUDED.page_number,
                                evidence = EXCLUDED.evidence
                            WHERE circular_link.status = 'PROPOSED'
                        """,
                        (lineage.link_id(document_id, citation.normalized), document_id, citation.relation,
                         citation.identifier, citation.normalized, target, citation.page_number, citation.evidence))
                    proposed += 1
            identified = sum(1 for own in own_by_document.values() if own)
        return {"circulars": len(pages), "identified": identified, "links": proposed}

    def list(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT l.id::text, l.relation, l.cited_identifier, l.page_number, l.evidence, l.status, l.decided_by,
                       l.decided_at, l.retired_obligations, l.created_at,
                       s.id, s.regulator, s.title, s.source_url, t.id, t.regulator, t.title, t.source_url,
                       (SELECT count(*) FROM obligation o WHERE o.document_id = t.id AND o.lifecycle_status = 'ACTIVE'),
                       (SELECT string_agg(i.identifier, ', ') FROM document_identifier i WHERE i.document_id = s.id)
                FROM circular_link l
                JOIN regulatory_document s ON s.id = l.source_document_id
                LEFT JOIN regulatory_document t ON t.id = l.target_document_id
                ORDER BY CASE l.status WHEN 'PROPOSED' THEN 0 WHEN 'CONFIRMED' THEN 1 ELSE 2 END,
                         CASE l.relation WHEN 'SUPERSEDES' THEN 0 WHEN 'WITHDRAWS' THEN 0 WHEN 'AMENDS' THEN 1 ELSE 2 END,
                         l.created_at DESC
                """).fetchall()
        return [{
            "id": row[0], "relation": row[1], "citedIdentifier": row[2], "pageNumber": row[3], "evidence": row[4],
            "status": row[5], "decidedBy": row[6], "decidedAt": row[7], "retiredObligations": row[8],
            "createdAt": row[9], "retires": row[1] in lineage.RETIRING and row[14] is not None,
            "source": {"id": row[10], "regulator": row[11], "title": row[12], "sourceUrl": row[13],
                       "identifiers": row[19]},
            "target": None if row[14] is None else {"id": row[14], "regulator": row[15], "title": row[16],
                                                     "sourceUrl": row[17], "activeObligations": row[18]},
        } for row in rows]

    def _link(self, cursor, link_id: str, lock: bool = False):
        row = cursor.execute(
            f"""
            SELECT id::text, relation, source_document_id, target_document_id, status FROM circular_link
            WHERE id = %s {'FOR UPDATE' if lock else ''}
            """, (link_id,)).fetchone()
        if row is None:
            raise LinkNotFound(link_id)
        return row

    def decide(self, link_id: str, confirm: bool, decided_by: str) -> dict:
        """Confirm or dismiss a proposed link. Confirming a SUPERSEDES or WITHDRAWS link retires the
        earlier circular's active obligations and closes their findings that are still pending review."""
        with self._connect() as connection, connection.cursor() as cursor:
            _, relation, source, target, status = self._link(cursor, link_id, lock=True)
            if status != "PROPOSED":
                raise LinkAlreadyDecided(link_id)
            retired = 0
            if confirm and relation in lineage.RETIRING and target:
                retired_ids = [row[0] for row in cursor.execute(
                    """
                    UPDATE obligation SET lifecycle_status = 'RETIRED', retired_by_link = %s, retired_at = now()
                    WHERE document_id = %s AND lifecycle_status = 'ACTIVE' RETURNING id
                    """, (link_id, target)).fetchall()]
                retired = len(retired_ids)
                if retired_ids:
                    cursor.execute(
                        "UPDATE finding SET status = 'SUPERSEDED' WHERE obligation_id = ANY(%s) AND status = 'PENDING_REVIEW'",
                        (retired_ids,))
            cursor.execute(
                """
                UPDATE circular_link SET status = %s, decided_by = %s, decided_at = now(), retired_obligations = %s
                WHERE id = %s
                """, ("CONFIRMED" if confirm else "DISMISSED", decided_by, retired, link_id))
        if confirm and target and self._graph is not None and hasattr(self._graph, "save_link"):
            try:
                self._graph.save_link(link_id, source, target, relation)
            except Exception:
                logger.exception("Could not write confirmed link %s to Neo4j", link_id)
        return next(item for item in self.list() if item["id"] == link_id)

    def diff(self, link_id: str, embedder: Embedder) -> dict:
        with self._connect() as connection, connection.cursor() as cursor:
            _, relation, source, target, _ = self._link(cursor, link_id)
            if target is None:
                return {"relation": relation, "available": False, "changes": [],
                        "message": "The cited circular has not been ingested, so there is nothing to compare."}

            def obligations(document_id):
                return [{"id": row[0], "summary": row[1], "quotedText": row[2], "pageNumber": row[3],
                         "lifecycleStatus": row[4]} for row in cursor.execute(
                    """
                    SELECT o.id::text, o.summary, c.quoted_text, c.page_number, o.lifecycle_status FROM obligation o
                    LEFT JOIN LATERAL (SELECT quoted_text, page_number FROM citation
                                       WHERE obligation_id = o.id LIMIT 1) c ON true
                    WHERE o.document_id = %s ORDER BY c.page_number, o.summary
                    """, (document_id,)).fetchall()]

            before, after = obligations(target), obligations(source)
        items = before + after
        if items:
            for item, vector in zip(items, embedder.embed([item["summary"] for item in items]), strict=True):
                item["embedding"] = vector
        changes = lineage.diff_obligations(before, after)
        counts = {kind: sum(1 for item in changes if item["change"] == kind)
                  for kind in ("NEW", "MODIFIED", "REMOVED", "UNCHANGED")}
        return {"relation": relation, "available": True, "counts": counts, "changes": changes}
