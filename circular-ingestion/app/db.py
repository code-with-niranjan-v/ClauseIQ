import json
import uuid
from pathlib import Path
from typing import Protocol

import psycopg
from pgvector.psycopg import register_vector

from app.embeddings import Embedder
from app.knowledge import CONTROL_DOCUMENT_ID, POLICY_DOCUMENT_ID, Knowledge, control_text
from app.models import ControlEvidence, IngestionEvent, IngestionResult, PolicyEvidence

SCHEMA = Path(__file__).with_name("schema.sql")


class Repository(Protocol):
    def begin_event(self, event: IngestionEvent) -> bool: ...
    def save_result(self, event: IngestionEvent, result: IngestionResult) -> None: ...
    def fail_event(self, event: IngestionEvent, error: str, final: bool) -> None: ...


class PostgresRepository:
    """Authoritative store for processing state, chunks, obligations and citations."""

    def __init__(self, database_url: str, embedding_dimensions: int) -> None:
        self._url = database_url
        self._dimensions = embedding_dimensions

    def _connect(self, vectors: bool = True) -> psycopg.Connection:
        connection = psycopg.connect(self._url, connect_timeout=10)
        if vectors:
            register_vector(connection)
        return connection

    def ensure_schema(self) -> None:
        with self._connect(vectors=False) as connection:
            connection.execute(SCHEMA.read_text().format(dimensions=self._dimensions))

    def ping(self) -> None:
        with self._connect(vectors=False) as connection:
            connection.execute("SELECT 1")

    # Internal knowledge -------------------------------------------------

    def seed_knowledge(self, knowledge: Knowledge, embedder: Embedder, embedding_label: str) -> bool:
        """Load the handbook, controls and roles. Returns False when they are already current.

        Embeddings are only requested when the files or the embedding model changed.
        """
        checksum = f"{knowledge.checksum}:{embedding_label}"
        with self._connect() as connection, connection.cursor() as cursor:
            current = cursor.execute(
                "SELECT checksum FROM internal_document WHERE id = %s", (POLICY_DOCUMENT_ID,)).fetchone()
            if current and current[0] == checksum:
                return False
            policy_vectors = embedder.embed([item.content for item in knowledge.policies])
            control_vectors = embedder.embed([control_text(item) for item in knowledge.controls])
            cursor.execute("DELETE FROM document_chunk WHERE document_id = ANY(%s)",
                           ([POLICY_DOCUMENT_ID, CONTROL_DOCUMENT_ID],))
            for identifier, kind, title in ((POLICY_DOCUMENT_ID, "POLICY", knowledge.title),
                                            (CONTROL_DOCUMENT_ID, "CONTROL", "Control register")):
                cursor.execute(
                    """
                    INSERT INTO internal_document (id, document_type, title, checksum, approval_status)
                    VALUES (%s, %s, %s, %s, 'APPROVED')
                    ON CONFLICT (id) DO UPDATE
                        SET title = EXCLUDED.title, checksum = EXCLUDED.checksum, updated_at = now()
                    """,
                    (identifier, kind, title, checksum))
            cursor.executemany(
                "INSERT INTO organizational_role (name) VALUES (%s) ON CONFLICT DO NOTHING",
                [(role,) for role in knowledge.roles])
            cursor.executemany(
                """
                INSERT INTO control (id, name, description, owner_role, frequency, policy_section)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                    SET name = EXCLUDED.name, description = EXCLUDED.description, owner_role = EXCLUDED.owner_role,
                        frequency = EXCLUDED.frequency, policy_section = EXCLUDED.policy_section
                """,
                [(item.control_id, item.name, item.description, item.owner_role, item.frequency,
                  item.policy_section) for item in knowledge.controls])
            cursor.execute("DELETE FROM control WHERE NOT (id = ANY(%s))",
                           ([item.control_id for item in knowledge.controls],))
            cursor.executemany(
                """
                INSERT INTO document_chunk
                    (id, document_id, document_type, section_number, heading, content, embedding, approval_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'APPROVED')
                """,
                [(item.chunk_id, POLICY_DOCUMENT_ID, "POLICY", item.section_number, item.heading, item.content,
                  _vector(vector)) for item, vector in zip(knowledge.policies, policy_vectors, strict=True)]
                + [(_uuid("control", item.control_id), CONTROL_DOCUMENT_ID, "CONTROL", item.control_id, item.name,
                    control_text(item), _vector(vector))
                   for item, vector in zip(knowledge.controls, control_vectors, strict=True)])
            return True

    def search_policies(self, embedding: list[float], limit: int) -> list[PolicyEvidence]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, document_id, section_number, heading, content, 1 - (embedding <=> %(query)s)
                FROM document_chunk
                WHERE document_type = 'POLICY' AND approval_status = 'APPROVED'
                ORDER BY embedding <=> %(query)s LIMIT %(limit)s
                """,
                {"query": _vector(embedding), "limit": limit}).fetchall()
        return [PolicyEvidence(chunk_id=str(row[0]), document_id=row[1], section_number=row[2], heading=row[3],
                               content=row[4], similarity=float(row[5])) for row in rows]

    def search_controls(self, embedding: list[float], limit: int) -> list[ControlEvidence]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.name, c.description, c.owner_role, c.frequency, c.policy_section,
                       1 - (k.embedding <=> %(query)s)
                FROM document_chunk k JOIN control c ON c.id = k.section_number
                WHERE k.document_type = 'CONTROL' AND k.approval_status = 'APPROVED'
                ORDER BY k.embedding <=> %(query)s LIMIT %(limit)s
                """,
                {"query": _vector(embedding), "limit": limit}).fetchall()
        return [ControlEvidence(control_id=row[0], name=row[1], description=row[2], owner_role=row[3],
                                frequency=row[4], policy_section=row[5], similarity=float(row[6])) for row in rows]

    def roles(self) -> list[str]:
        with self._connect(vectors=False) as connection:
            return [row[0] for row in connection.execute("SELECT name FROM organizational_role ORDER BY name")]

    def begin_event(self, event: IngestionEvent) -> bool:
        """Claim the event. Returns False when it has already been processed.

        The scanner delivers at least once and can resend an eventId, so a
        completed event must be skipped rather than processed again.
        """
        with self._connect(vectors=False) as connection:
            claimed = connection.execute(
                """
                INSERT INTO processed_event (event_id, document_id, document_version_id, status, attempts)
                VALUES (%s, %s, %s, 'PROCESSING', 1)
                ON CONFLICT (event_id) DO UPDATE
                    SET status = 'PROCESSING', attempts = processed_event.attempts + 1, started_at = now()
                    WHERE processed_event.status <> 'COMPLETED'
                RETURNING event_id
                """,
                (event.event_id, event.document_id, event.document_version_id),
            ).fetchone()
            if claimed is None:
                return False
            connection.execute(
                """
                INSERT INTO regulatory_document (id, regulator, title, source_url) VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                    SET regulator = EXCLUDED.regulator, title = EXCLUDED.title,
                        source_url = EXCLUDED.source_url, updated_at = now()
                """,
                (event.document_id, event.regulator, event.title, event.source_url),
            )
            connection.execute(
                """
                INSERT INTO regulatory_document_version
                    (id, document_id, minio_bucket, minio_object_key, checksum, processing_status)
                VALUES (%s, %s, %s, %s, %s, 'PROCESSING')
                ON CONFLICT (id) DO UPDATE SET processing_status = 'PROCESSING'
                    WHERE regulatory_document_version.processing_status <> 'COMPLETED'
                """,
                (event.document_version_id, event.document_id, event.minio_bucket,
                 event.minio_object_key, event.checksum),
            )
            return True

    def save_result(self, event: IngestionEvent, result: IngestionResult) -> None:
        """Replace this version's chunks and obligations and mark the event completed, in one transaction."""
        with self._connect() as connection, connection.cursor() as cursor:
            # Deleting chunks cascades to obligations and citations from an earlier, failed attempt.
            cursor.execute("DELETE FROM document_chunk WHERE document_version_id = %s", (result.document_version_id,))
            cursor.executemany(
                """
                INSERT INTO document_chunk
                    (id, document_id, document_version_id, document_type, page_number, clause_number, heading,
                     content, start_offset, end_offset, embedding, metadata, approval_status)
                VALUES (%s, %s, %s, 'CIRCULAR', %s, %s, %s, %s, %s, %s, %s, %s, 'APPROVED')
                """,
                [(chunk.id, chunk.document_id, chunk.document_version_id, chunk.page_number, chunk.clause_number,
                  chunk.heading, chunk.content, chunk.start_offset, chunk.end_offset,
                  _vector(chunk.embedding),
                  json.dumps({"regulator": event.regulator, "title": event.title, "sourceUrl": event.source_url}))
                 for chunk in result.chunks],
            )
            cursor.executemany(
                """
                INSERT INTO obligation
                    (id, document_id, document_version_id, chunk_id, summary, required_action, responsible_entity,
                     deadline, applicability, confidence, extraction_method)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [(item.obligation_id, result.document_id, result.document_version_id, item.chunk_id, item.summary,
                  item.required_action, item.responsible_entity, item.deadline, item.applicability,
                  item.confidence, item.extraction_method)
                 for item in result.obligations],
            )
            cursor.executemany(
                """
                INSERT INTO citation
                    (id, obligation_id, document_id, document_version_id, page_number, clause_number,
                     quoted_text, start_offset, end_offset)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [(str(uuid.uuid5(uuid.NAMESPACE_URL, f"clauseiq:citation:{item.obligation_id}")),
                  item.obligation_id, result.document_id, result.document_version_id, item.citation.page_number,
                  item.citation.clause_number, item.citation.quoted_text, item.citation.start_offset,
                  item.citation.end_offset)
                 for item in result.obligations],
            )
            cursor.executemany(
                "UPDATE obligation SET coverage_status = %s, coverage_explanation = %s WHERE id = %s",
                [(item.coverage_status, item.explanation, item.obligation_id) for item in result.assessments],
            )
            cursor.executemany(
                """
                INSERT INTO obligation_mapping
                    (id, obligation_id, target_type, target_id, section_number, similarity, matched)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [(_uuid("mapping", item.obligation_id, kind, target), item.obligation_id, kind, target,
                  section, similarity, matched)
                 for item in result.assessments
                 for kind, target, section, similarity, matched in (
                     [("POLICY_SECTION", policy.chunk_id, policy.section_number, policy.similarity, policy.matched)
                      for policy in item.policies]
                     + [("CONTROL", control.control_id, control.policy_section, control.similarity, control.matched)
                        for control in item.controls])],
            )
            findings = [item for item in result.assessments if item.finding_type and item.recommendation]
            cursor.executemany(
                """
                INSERT INTO finding
                    (id, obligation_id, document_id, document_version_id, finding_type, coverage_status, severity,
                     title, explanation, policy_section, policy_quote, confidence, original_ai_output)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [(_uuid("finding", item.obligation_id), item.obligation_id, result.document_id,
                  result.document_version_id, item.finding_type, item.coverage_status, item.severity,
                  item.recommendation.gap_title, item.explanation, item.policy_section, item.policy_quote,
                  item.confidence, json.dumps(item.original_ai_output))
                 for item in findings],
            )
            cursor.executemany(
                """
                INSERT INTO recommendation
                    (id, finding_id, draft_policy_text, recommended_action, assigned_role, suggested_deadline,
                     required_evidence, confidence, original_ai_output)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [(_uuid("recommendation", item.obligation_id), _uuid("finding", item.obligation_id),
                  item.recommendation.draft_policy_text, item.recommendation.recommended_action,
                  item.recommendation.assigned_role, item.recommendation.suggested_deadline,
                  json.dumps(item.recommendation.required_evidence), item.recommendation.confidence,
                  json.dumps(item.recommendation.original_ai_output))
                 for item in findings],
            )
            cursor.execute(
                """
                UPDATE regulatory_document_version
                SET processing_status = 'COMPLETED', page_count = %s, obligation_count = %s,
                    rejected_obligation_count = %s, processed_at = now()
                WHERE id = %s
                """,
                (result.page_count, len(result.obligations), len(result.rejected), result.document_version_id),
            )
            cursor.execute(
                """
                UPDATE processed_event SET status = 'COMPLETED', last_error = NULL, completed_at = now()
                WHERE event_id = %s
                """,
                (event.event_id,),
            )

    def fail_event(self, event: IngestionEvent, error: str, final: bool) -> None:
        with self._connect(vectors=False) as connection:
            connection.execute(
                "UPDATE processed_event SET status = %s, last_error = %s WHERE event_id = %s AND status <> 'COMPLETED'",
                ("DEAD_LETTERED" if final else "FAILED", error[:2000], event.event_id),
            )
            connection.execute(
                """
                UPDATE regulatory_document_version SET processing_status = 'FAILED'
                WHERE id = %s AND processing_status <> 'COMPLETED'
                """,
                (event.document_version_id,),
            )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "clauseiq:" + ":".join(parts)))


def _vector(embedding: list[float] | None):
    if embedding is None:
        return None
    from pgvector import Vector

    return Vector(embedding)
