import json
import uuid
from pathlib import Path
from typing import Protocol

import psycopg
from pgvector.psycopg import register_vector

from app.models import IngestionEvent, IngestionResult

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


def _vector(embedding: list[float] | None):
    if embedding is None:
        return None
    from pgvector import Vector

    return Vector(embedding)
