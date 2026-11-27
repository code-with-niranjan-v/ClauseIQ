"""Runs against a real PostgreSQL with pgvector when TEST_DATABASE_URL is set."""
import json
import os
import uuid

import psycopg
import pytest

from app.db import PostgresRepository
from app.embeddings import HashEmbedder
from app.lineage_store import LineageStore, LinkAlreadyDecided

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")


class Graph:
    def __init__(self):
        self.links = []

    def save_link(self, link_id, source, target, relation):
        self.links.append((source, target, relation))


def circular(connection, title, text, obligations):
    document, version = f"doc-{uuid.uuid4()}", f"ver-{uuid.uuid4()}"
    connection.execute("INSERT INTO regulatory_document (id, regulator, title, source_url) VALUES (%s, 'IRDAI', %s, '')",
                       (document, title))
    connection.execute(
        """INSERT INTO regulatory_document_version (id, document_id, minio_bucket, minio_object_key, checksum,
                                                    processing_status) VALUES (%s, %s, 'b', 'k', 'c', 'COMPLETED')""",
        (version, document))
    chunk = uuid.uuid4()
    connection.execute(
        """INSERT INTO document_chunk (id, document_id, document_version_id, document_type, page_number, content,
                                       start_offset, approval_status) VALUES (%s, %s, %s, 'CIRCULAR', 1, %s, 0, 'APPROVED')""",
        (chunk, document, version, text))
    ids = []
    for summary in obligations:
        obligation = uuid.uuid4()
        connection.execute(
            """INSERT INTO obligation (id, document_id, document_version_id, chunk_id, summary, required_action,
                                       confidence, extraction_method) VALUES (%s, %s, %s, %s, %s, 'Do it', 0.9, 'LLM')""",
            (obligation, document, version, chunk, summary))
        connection.execute(
            """INSERT INTO citation (id, obligation_id, document_id, document_version_id, page_number, quoted_text)
               VALUES (%s, %s, %s, %s, 1, %s)""", (uuid.uuid4(), obligation, document, version, summary))
        ids.append(obligation)
    return document, ids


@pytest.fixture
def documents():
    PostgresRepository(URL, embedding_dimensions=64).ensure_schema()
    with psycopg.connect(URL) as connection:
        connection.execute("TRUNCATE circular_link, document_identifier, finding, obligation, citation, document_chunk, "
                           "regulatory_document_version, regulatory_document CASCADE")
        old, old_obligations = circular(
            connection, "Old master circular",
            "Ref: IRDAI/F&I/CIR/MISC/45/4/2026 Date: 10.04.2026\nSubject: Returns\nInsurers shall file returns "
            "within 30 days of the quarter end.",
            ["Insurers must file returns within 30 days", "Insurers must appoint a compliance officer"])
        new, _ = circular(
            connection, "New master circular",
            "Ref: IRDAI/F&I/CIR/MISC/142/11/2026 Date: 02.11.2026\nSubject: Master Circular\nInsurers shall file "
            "returns within 15 days.\nSchedule I - The following Circulars shall stand repealed:\n"
            "1. IRDAI/F&I/CIR/MISC/045/04/2026 dated 10.04.2026",
            ["Insurers must file returns within 15 days", "Insurers must appoint a compliance officer"])
        finding = uuid.uuid4()
        connection.execute(
            """INSERT INTO finding (id, obligation_id, document_id, document_version_id, finding_type, coverage_status,
                   severity, title, explanation, confidence, original_ai_output)
               SELECT %s, %s, document_id, document_version_id, 'POLICY_GAP', 'NOT_COVERED', 'HIGH', 't', 'e', 0.9, %s
               FROM obligation WHERE id = %s""", (finding, old_obligations[0], json.dumps({}), old_obligations[0]))
    return old, new, finding


def test_a_confirmed_repeal_retires_the_earlier_obligations(documents):
    old, new, finding = documents
    graph = Graph()
    store = LineageStore(URL, graph)

    assert store.refresh() == {"circulars": 2, "identified": 2, "links": 1}
    assert store.refresh()["links"] == 1   # idempotent
    [link] = store.list()
    assert (link["relation"], link["status"], link["source"]["id"], link["target"]["id"]) == (
        "WITHDRAWS", "PROPOSED", new, old)
    assert link["target"]["activeObligations"] == 2 and link["retires"]

    diff = store.diff(link["id"], HashEmbedder(64))
    assert diff["available"] and diff["counts"]["MODIFIED"] == 1   # 30 days became 15 days

    decided = store.decide(link["id"], confirm=True, decided_by="Meena (meena)")
    assert (decided["status"], decided["retiredObligations"], decided["decidedBy"]) == ("CONFIRMED", 2, "Meena (meena)")
    assert graph.links == [(new, old, "WITHDRAWS")]
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT DISTINCT lifecycle_status FROM obligation WHERE document_id = %s",
                                  (old,)).fetchall() == [("RETIRED",)]
        assert connection.execute("SELECT status FROM finding WHERE id = %s", (finding,)).fetchone() == ("SUPERSEDED",)
        assert connection.execute("SELECT count(*) FROM obligation WHERE document_id = %s AND lifecycle_status = 'ACTIVE'",
                                  (new,)).fetchone() == (2,)
    with pytest.raises(LinkAlreadyDecided):
        store.decide(link["id"], confirm=False, decided_by="someone else")
    # Re-detection keeps the decision.
    store.refresh()
    assert store.list()[0]["status"] == "CONFIRMED"


def test_a_dismissed_link_retires_nothing(documents):
    old, _, finding = documents
    store = LineageStore(URL)
    store.refresh()
    [link] = store.list()
    assert store.decide(link["id"], confirm=False, decided_by="Meena")["status"] == "DISMISSED"
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT count(*) FROM obligation WHERE document_id = %s AND lifecycle_status = 'ACTIVE'",
                                  (old,)).fetchone() == (2,)
        assert connection.execute("SELECT status FROM finding WHERE id = %s", (finding,)).fetchone() == ("PENDING_REVIEW",)
