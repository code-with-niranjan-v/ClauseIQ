"""PostgreSQL storage for system assessments, and the circular obligations they are compared with."""
import json
import uuid

import psycopg
from pgvector.psycopg import register_vector

from app.system_assessment import Artifact, AssessmentResult, CircularObligation, improvement_plan


def _floats(vector) -> list[float]:
    """pgvector returns numpy arrays or Vector objects depending on the version."""
    if hasattr(vector, "tolist"):
        return vector.tolist()
    return vector.to_list()


class SystemAssessmentStore:
    def __init__(self, database_url: str) -> None:
        self._url = database_url

    def _connect(self, vectors: bool = False) -> psycopg.Connection:
        connection = psycopg.connect(self._url, connect_timeout=10)
        if vectors:
            register_vector(connection)
        return connection

    # -- inputs

    def circular_obligations(self) -> list[CircularObligation]:
        with self._connect(vectors=True) as connection:
            rows = connection.execute(
                """
                SELECT o.id::text, o.summary, o.required_action, o.deadline, k.embedding, d.title, d.regulator,
                       d.source_url, c.quoted_text, c.page_number, c.clause_number
                FROM obligation o
                JOIN document_chunk k ON k.id = o.chunk_id
                JOIN regulatory_document d ON d.id = o.document_id
                LEFT JOIN LATERAL (SELECT quoted_text, page_number, clause_number FROM citation
                                   WHERE obligation_id = o.id LIMIT 1) c ON true
                WHERE k.embedding IS NOT NULL
                """).fetchall()
        return [CircularObligation(
            obligation_id=row[0], summary=row[1], required_action=row[2], deadline=row[3],
            embedding=_floats(row[4]), document_title=row[5], regulator=row[6], source_url=row[7],
            quoted_text=row[8], page_number=row[9], clause_number=row[10]) for row in rows]

    def roles(self) -> list[str]:
        with self._connect() as connection:
            return [row[0] for row in connection.execute("SELECT name FROM organizational_role ORDER BY name")]

    # -- lifecycle

    def create(self, name: str, artifacts: list[Artifact]) -> str:
        assessment_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO system_assessment (id, name, status, stage) VALUES (%s, %s, 'QUEUED', 'Waiting to start')",
                (assessment_id, name))
            for artifact in artifacts:
                connection.execute(
                    """
                    INSERT INTO system_artifact (id, assessment_id, kind, filename, content_type, checksum, size_bytes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (artifact.id, assessment_id, artifact.kind, artifact.filename, artifact.content_type,
                     artifact.checksum, len(artifact.data)))
        return assessment_id

    def stage(self, assessment_id: str, stage: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE system_assessment SET status = 'PROCESSING', stage = %s WHERE id = %s",
                               (stage, assessment_id))

    def fail(self, assessment_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE system_assessment SET status = 'FAILED', stage = NULL, error = %s, completed_at = now()
                WHERE id = %s
                """, (error[:2000], assessment_id))

    def interrupt_unfinished(self) -> int:
        """Assessments run in this process. After a restart, unfinished ones can never complete."""
        with self._connect() as connection:
            return connection.execute(
                """
                UPDATE system_assessment SET status = 'FAILED', stage = NULL, completed_at = now(),
                    error = 'The ingestion worker restarted before this assessment finished. Run it again.'
                WHERE status IN ('QUEUED', 'PROCESSING')
                """).rowcount

    def save(self, assessment_id: str, artifacts: list[Artifact], result: AssessmentResult) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            for artifact in artifacts:
                cursor.execute("UPDATE system_artifact SET method = %s, summary = %s WHERE id = %s",
                               (artifact.method, artifact.summary, artifact.id))
            cursor.executemany(
                "INSERT INTO system_fact (id, assessment_id, artifact_id, page_number, content) VALUES (%s, %s, %s, %s, %s)",
                [(fact.id, assessment_id, fact.artifact_id, fact.page_number, fact.content) for fact in result.facts])
            cursor.executemany(
                """
                INSERT INTO system_finding
                    (id, assessment_id, obligation_id, status, severity, title, explanation, improvement, owner_role,
                     effort, confidence, similarity, system_quote, evidence_fact_ids, original_ai_output)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s)
                """,
                [(str(uuid.uuid4()), assessment_id, item.obligation.obligation_id, item.status, item.severity,
                  item.title, item.explanation, item.improvement, item.owner_role, item.effort, item.confidence,
                  item.similarity, item.system_quote, [fact.id for fact in item.evidence],
                  json.dumps(item.original_ai_output)) for item in result.findings])
            cursor.execute(
                """
                UPDATE system_assessment SET status = 'COMPLETED', stage = NULL, completed_at = now(),
                    fact_count = %s, compared_count = %s, not_applicable_count = %s
                WHERE id = %s
                """, (len(result.facts), result.compared, result.not_applicable, assessment_id))

    # -- reading

    def list(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT a.id::text, a.name, a.status, a.stage, a.error, a.created_at, a.completed_at,
                       count(f.id) FILTER (WHERE f.status <> 'MEETS'),
                       count(f.id) FILTER (WHERE f.severity = 'HIGH')
                FROM system_assessment a LEFT JOIN system_finding f ON f.assessment_id = a.id
                GROUP BY a.id ORDER BY a.created_at DESC LIMIT 50
                """).fetchall()
        return [{"id": row[0], "name": row[1], "status": row[2], "stage": row[3], "error": row[4],
                 "createdAt": row[5], "completedAt": row[6], "openFindings": row[7], "highFindings": row[8]}
                for row in rows]

    def get(self, assessment_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id::text, name, status, stage, error, created_at, completed_at, fact_count, compared_count,
                       not_applicable_count FROM system_assessment WHERE id = %s
                """, (assessment_id,)).fetchone()
            if row is None:
                return None
            artifacts = connection.execute(
                """
                SELECT a.id::text, a.kind, a.filename, a.content_type, a.size_bytes, a.method, a.summary,
                       (SELECT count(*) FROM system_fact f WHERE f.artifact_id = a.id)
                FROM system_artifact a WHERE a.assessment_id = %s
                ORDER BY array_position(ARRAY['SRE', 'ARCHITECTURE', 'ER'], a.kind)
                """, (assessment_id,)).fetchall()
            facts = {fact[0]: fact for fact in connection.execute(
                """
                SELECT f.id::text, a.kind, a.filename, f.page_number, f.content
                FROM system_fact f JOIN system_artifact a ON a.id = f.artifact_id WHERE f.assessment_id = %s
                """, (assessment_id,)).fetchall()}
            findings = connection.execute(
                """
                SELECT s.id::text, s.status, s.severity, s.title, s.explanation, s.improvement, s.owner_role, s.effort,
                       s.confidence, s.similarity, s.system_quote, s.evidence_fact_ids::text[],
                       o.id::text, o.summary, o.required_action, o.deadline, d.title, d.regulator, d.source_url,
                       c.quoted_text, c.page_number, c.clause_number
                FROM system_finding s
                JOIN obligation o ON o.id = s.obligation_id
                JOIN regulatory_document d ON d.id = o.document_id
                LEFT JOIN LATERAL (SELECT quoted_text, page_number, clause_number FROM citation
                                   WHERE obligation_id = o.id LIMIT 1) c ON true
                WHERE s.assessment_id = %s
                ORDER BY array_position(ARRAY['HIGH', 'MEDIUM', 'LOW'], s.severity) NULLS LAST, s.similarity DESC
                """, (assessment_id,)).fetchall()

        def fact(identifier):
            item = facts.get(identifier)
            return item and {"id": item[0], "kind": item[1], "filename": item[2], "pageNumber": item[3],
                             "content": item[4]}

        items = [{
            "id": item[0], "status": item[1], "severity": item[2], "title": item[3], "explanation": item[4],
            "improvement": item[5], "ownerRole": item[6], "effort": item[7], "confidence": item[8],
            "similarity": item[9], "systemQuote": item[10],
            "evidence": [entry for entry in (fact(identifier) for identifier in item[11]) if entry],
            "obligation": {"id": item[12], "summary": item[13], "requiredAction": item[14], "deadline": item[15],
                           "quotedText": item[19], "pageNumber": item[20], "clauseNumber": item[21],
                           "circular": {"title": item[16], "regulator": item[17], "sourceUrl": item[18]}},
        } for item in findings]
        open_items = [item for item in items if item["status"] != "MEETS"]
        return {
            "id": row[0], "name": row[1], "status": row[2], "stage": row[3], "error": row[4], "createdAt": row[5],
            "completedAt": row[6],
            "stats": {"facts": row[7], "compared": row[8], "notApplicable": row[9], "meets": len(items) - len(open_items),
                      "open": len(open_items)},
            "artifacts": [{"id": item[0], "kind": item[1], "filename": item[2], "contentType": item[3],
                           "sizeBytes": item[4], "method": item[5], "summary": item[6], "factCount": item[7]}
                          for item in artifacts],
            "findings": items,
            "plan": improvement_plan(open_items),
        }
