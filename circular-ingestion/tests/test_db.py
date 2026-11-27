"""Runs against a real PostgreSQL with pgvector when TEST_DATABASE_URL is set."""
import os

import psycopg
import pytest

from app import workflow
from app.consumer import EventProcessor
from app.db import PostgresRepository
from app.embeddings import HashEmbedder
from app.extraction import RuleBasedExtractor
from tests.fakes import MemoryStore, make_event

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")
TABLES = "citation, obligation, document_chunk, regulatory_document_version, regulatory_document, processed_event"


@pytest.fixture
def repository():
    repository = PostgresRepository(URL, embedding_dimensions=64)
    repository.ensure_schema()
    repository.ensure_schema()  # safe to run on every start
    with psycopg.connect(URL) as connection:
        connection.execute(f"TRUNCATE {TABLES}")
    return repository


def processor(repository, pdf, event, graph=None):
    pipeline = workflow.build_workflow(workflow.Dependencies(
        store=MemoryStore({(event.minio_bucket, event.minio_object_key): pdf}),
        extractor=RuleBasedExtractor(), embedder=HashEmbedder(64), repository=repository, graph=graph))
    return EventProcessor(repository, pipeline, max_attempts=2, backoff_seconds=0, sleep=lambda _: None)


def counts() -> dict:
    with psycopg.connect(URL) as connection:
        return {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("document_chunk", "obligation", "citation")}


def test_results_are_stored_and_a_resent_event_changes_nothing(repository, sample_pdf):
    event = make_event(sample_pdf)

    assert processor(repository, sample_pdf, event).process(event) == "COMPLETED"
    first = counts()
    assert processor(repository, sample_pdf, event).process(event) == "SKIPPED"

    assert counts() == first
    assert first["obligation"] == first["citation"] >= 4
    with psycopg.connect(URL) as connection:
        status, attempts = connection.execute(
            "SELECT status, attempts FROM processed_event WHERE event_id = %s", (event.event_id,)).fetchone()
        version = connection.execute(
            "SELECT processing_status, page_count, obligation_count FROM regulatory_document_version").fetchone()
        mismatched = connection.execute(
            """
            SELECT count(*) FROM citation c JOIN obligation o ON o.id = c.obligation_id
            JOIN document_chunk k ON k.id = o.chunk_id
            WHERE position(c.quoted_text in k.content) = 0 OR c.page_number <> k.page_number
            """).fetchone()[0]
    assert (status, attempts) == ("COMPLETED", 1)
    assert version == ("COMPLETED", 2, first["obligation"])
    assert mismatched == 0


def test_vector_search_returns_the_matching_clause(repository, sample_pdf):
    event = make_event(sample_pdf)
    processor(repository, sample_pdf, event).process(event)
    from pgvector import Vector
    from pgvector.psycopg import register_vector

    query = Vector(HashEmbedder(64).embed(["report a security incident to the regulator"])[0])
    with psycopg.connect(URL) as connection:
        register_vector(connection)
        clause = connection.execute(
            """
            SELECT clause_number FROM document_chunk
            WHERE document_type = 'CIRCULAR' ORDER BY embedding <=> %s LIMIT 1
            """, (query,)).fetchone()[0]
    assert clause == "5.1"


class FailingGraph:
    def save(self, event, result):
        raise ConnectionError("Neo4j unavailable")


def test_failed_document_leaves_no_partial_results(repository, sample_pdf):
    event = make_event(sample_pdf)

    assert processor(repository, sample_pdf, event, graph=FailingGraph()).process(event) == "DEAD_LETTERED"

    assert counts() == {"document_chunk": 0, "obligation": 0, "citation": 0}
    with psycopg.connect(URL) as connection:
        row = connection.execute("SELECT status, attempts, last_error FROM processed_event").fetchone()
        version = connection.execute("SELECT processing_status FROM regulatory_document_version").fetchone()[0]
    assert row[:2] == ("DEAD_LETTERED", 2) and "Neo4j unavailable" in row[2]
    assert version == "FAILED"
    # The dead-lettered event can be replayed once the cause is fixed.
    assert processor(repository, sample_pdf, event).process(event) == "COMPLETED"
