from typing import Protocol

from app.config import Settings
from app.models import IngestionEvent, IngestionResult


class GraphStore(Protocol):
    def save(self, event: IngestionEvent, result: IngestionResult) -> None: ...


class NoGraphStore:
    """Used when NEO4J_URI is empty."""

    def save(self, event: IngestionEvent, result: IngestionResult) -> None:
        return None


class Neo4jStore:
    """Traceability graph: RegulatoryDocument -CONTAINS-> Clause -CREATES-> Obligation.

    Full text and workflow status stay in PostgreSQL. Nodes carry the PostgreSQL
    ids (document, document_chunk, obligation) so the two stores can be joined.
    """

    def __init__(self, settings: Settings) -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))

    def ensure_schema(self) -> None:
        with self._driver.session() as session:
            for label in ("RegulatoryDocument", "Clause", "Obligation"):
                session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")

    def close(self) -> None:
        self._driver.close()

    def save(self, event: IngestionEvent, result: IngestionResult) -> None:
        # Only clauses that carry a detected number or an obligation become nodes.
        cited = {item.chunk_id for item in result.obligations}
        clauses = [
            {"id": chunk.id, "clauseNumber": chunk.clause_number, "heading": chunk.heading,
             "pageNumber": chunk.page_number}
            for chunk in result.chunks if chunk.clause_number or chunk.id in cited
        ]
        obligations = [
            {"id": item.obligation_id, "clauseId": item.chunk_id, "summary": item.summary,
             "requiredAction": item.required_action, "responsibleEntity": item.responsible_entity,
             "deadline": item.deadline, "pageNumber": item.citation.page_number,
             "clauseNumber": item.citation.clause_number, "confidence": item.confidence}
            for item in result.obligations
        ]
        with self._driver.session() as session:
            session.execute_write(_write, event, clauses, obligations)


def _write(transaction, event: IngestionEvent, clauses: list[dict], obligations: list[dict]) -> None:
    # Clear what an earlier attempt wrote for this version, so a retry cannot leave stale nodes.
    transaction.run(
        """
        MATCH (c:Clause {documentVersionId: $versionId})
        OPTIONAL MATCH (c)-[:CREATES]->(o:Obligation)
        DETACH DELETE o, c
        """,
        versionId=event.document_version_id,
    )
    transaction.run(
        """
        MERGE (d:RegulatoryDocument {id: $documentId})
        SET d.title = $title, d.regulator = $regulator, d.sourceUrl = $sourceUrl,
            d.latestVersionId = $versionId
        WITH d
        UNWIND $clauses AS clause
        MERGE (c:Clause {id: clause.id})
        SET c.clauseNumber = clause.clauseNumber, c.heading = clause.heading,
            c.pageNumber = clause.pageNumber, c.documentId = $documentId, c.documentVersionId = $versionId
        MERGE (d)-[:CONTAINS]->(c)
        """,
        documentId=event.document_id, versionId=event.document_version_id, title=event.title,
        regulator=event.regulator, sourceUrl=event.source_url, clauses=clauses,
    )
    transaction.run(
        """
        UNWIND $obligations AS obligation
        MATCH (c:Clause {id: obligation.clauseId})
        MERGE (o:Obligation {id: obligation.id})
        SET o.summary = obligation.summary, o.requiredAction = obligation.requiredAction,
            o.responsibleEntity = obligation.responsibleEntity, o.deadline = obligation.deadline,
            o.pageNumber = obligation.pageNumber, o.clauseNumber = obligation.clauseNumber,
            o.confidence = obligation.confidence, o.documentId = $documentId, o.documentVersionId = $versionId
        MERGE (c)-[:CREATES]->(o)
        """,
        documentId=event.document_id, versionId=event.document_version_id, obligations=obligations,
    )


def build_graph_store(settings: Settings) -> GraphStore:
    return Neo4jStore(settings) if settings.neo4j_uri else NoGraphStore()
