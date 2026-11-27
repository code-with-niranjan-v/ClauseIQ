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
TABLES = ("recommendation, finding, obligation_mapping, citation, obligation, document_chunk, control, "
          "organizational_role, internal_document, regulatory_document_version, regulatory_document, processed_event")


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


class CountingEmbedder(HashEmbedder):
    calls = 0

    def embed(self, texts):
        self.calls += 1
        return super().embed(texts)


def test_knowledge_is_seeded_once_and_findings_are_stored(repository):
    from app import knowledge
    from tests.test_assessment import DATA, build_pipeline

    embedder = CountingEmbedder(64)
    loaded = knowledge.load(DATA)
    assert repository.seed_knowledge(loaded, embedder, "hash:64") is True
    assert repository.seed_knowledge(loaded, embedder, "hash:64") is False  # unchanged files are not re-embedded
    assert embedder.calls == 2
    assert repository.roles() == sorted(loaded.roles)
    query = embedder.embed(["review audit logs for regulated systems every quarter"])[0]
    assert repository.search_policies(query, 1)[0].heading == "Audit logging"
    assert repository.search_controls(query, 1)[0].control_id == "CTRL-003"

    event, pipeline, _ = build_pipeline(repository=repository, knowledge_base=repository, dimensions=64)
    runner = EventProcessor(repository, pipeline, max_attempts=1, backoff_seconds=0, sleep=lambda _: None)
    assert runner.process(event) == "COMPLETED"
    assert runner.process(event) == "SKIPPED"

    with psycopg.connect(URL) as connection:
        coverage = dict(connection.execute(
            """
            SELECT c.clause_number, o.coverage_status FROM obligation o JOIN citation c ON c.obligation_id = o.id
            """).fetchall())
        findings = connection.execute(
            """
            SELECT c.clause_number, f.finding_type, f.severity, f.status, r.assigned_role, f.policy_section
            FROM finding f JOIN citation c ON c.obligation_id = f.obligation_id
            JOIN recommendation r ON r.finding_id = f.id ORDER BY c.clause_number
            """).fetchall()
        mappings = connection.execute(
            "SELECT target_type, count(*) FILTER (WHERE matched), count(*) FROM obligation_mapping GROUP BY 1 ORDER BY 1"
        ).fetchall()
        chatbot_visible = connection.execute(
            "SELECT count(*) FROM document_chunk WHERE document_type = 'POLICY' AND approval_status = 'APPROVED'"
        ).fetchone()[0]
        original = connection.execute(
            """
            SELECT r.original_ai_output->>'assignedRole' FROM recommendation r JOIN finding f ON f.id = r.finding_id
            WHERE f.finding_type = 'POLICY_GAP'
            """).fetchone()[0]
    assert coverage == {"2.1": "COVERED", "2.2": "CONFLICTING", "3.1": "PARTIALLY_COVERED",
                        "4.1": "PARTIALLY_COVERED", "5.1": "NOT_COVERED"}
    assert findings == [
        ("2.2", "POLICY_CONFLICT", "HIGH", "PENDING_REVIEW", "SOC Manager", "3"),
        ("3.1", "PARTIAL_POLICY_GAP", "MEDIUM", "PENDING_REVIEW", "SOC Manager", "6"),
        ("4.1", "OWNERSHIP_GAP", "MEDIUM", "PENDING_REVIEW", "SOC Manager", "7"),
        ("5.1", "POLICY_GAP", "HIGH", "PENDING_REVIEW", "Compliance Officer", None),
    ]
    assert mappings == [("CONTROL", 4, 15), ("POLICY_SECTION", 4, 20)]
    assert chatbot_visible == 8  # only the handbook sections; drafted policy text is never a POLICY chunk
    assert original == "Chief Risk Wizard"
