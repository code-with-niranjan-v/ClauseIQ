import uuid
from typing import Protocol

from app.config import Settings
from app.knowledge import POLICY_DOCUMENT_ID, Knowledge
from app.models import IngestionEvent, IngestionResult


class GraphStore(Protocol):
    def save(self, event: IngestionEvent, result: IngestionResult) -> None: ...
    def seed_knowledge(self, knowledge: Knowledge) -> None: ...


class NoGraphStore:
    """Used when NEO4J_URI is empty."""

    def seed_knowledge(self, knowledge: Knowledge) -> None:
        return None

    def save(self, event: IngestionEvent, result: IngestionResult) -> None:
        return None

    def save_link(self, link_id: str, source_id: str, target_id: str, relation: str) -> None:
        return None


class Neo4jStore:
    """Traceability graph with the nodes and relationships listed in PLAN.md.

    Full text and workflow status stay in PostgreSQL. Nodes carry the PostgreSQL
    ids (document, document_chunk, obligation, control, finding) so the stores can be joined.
    """

    def __init__(self, settings: Settings) -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))

    def ensure_schema(self) -> None:
        with self._driver.session() as session:
            for label in ("RegulatoryDocument", "Clause", "Obligation", "Policy", "PolicySection", "Control",
                          "Finding", "Recommendation"):
                session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:Role) REQUIRE n.name IS UNIQUE")

    def seed_knowledge(self, knowledge: Knowledge) -> None:
        sections = [{"id": item.chunk_id, "sectionNumber": item.section_number, "heading": item.heading}
                    for item in knowledge.policies]
        controls = [{"id": item.control_id, "name": item.name, "frequency": item.frequency,
                     "ownerRole": item.owner_role, "policySection": item.policy_section}
                    for item in knowledge.controls]
        with self._driver.session() as session:
            session.execute_write(_seed, knowledge.title, knowledge.roles, sections, controls)

    def close(self) -> None:
        self._driver.close()

    def save_link(self, link_id: str, source_id: str, target_id: str, relation: str) -> None:
        """A reviewer-confirmed relationship between two circulars. The relation is one of a fixed set."""
        if relation not in {"SUPERSEDES", "WITHDRAWS", "AMENDS", "REFERS_TO"}:
            raise ValueError(relation)
        with self._driver.session() as session:
            session.run(
                f"""
                MERGE (s:RegulatoryDocument {{id: $source}})
                MERGE (t:RegulatoryDocument {{id: $target}})
                MERGE (s)-[r:{relation}]->(t)
                SET r.linkId = $link, r.confirmedAt = datetime()
                """, source=source_id, target=target_id, link=link_id)

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
        by_obligation = {item.obligation_id: item for item in result.assessments}
        for row in obligations:
            assessed = by_obligation.get(row["id"])
            row["coverageStatus"] = assessed.coverage_status if assessed else None
        mappings = [
            {"obligationId": item.obligation_id,
             "sections": [policy.chunk_id for policy in item.policies if policy.matched],
             "controls": [control.control_id for control in item.controls if control.matched]}
            for item in result.assessments
        ]
        findings = [
            {"id": _uuid("finding", item.obligation_id), "obligationId": item.obligation_id,
             "findingType": item.finding_type, "coverageStatus": item.coverage_status, "severity": item.severity,
             "title": item.recommendation.gap_title,
             "recommendationId": _uuid("recommendation", item.obligation_id),
             "recommendedAction": item.recommendation.recommended_action,
             "assignedRole": item.recommendation.assigned_role}
            for item in result.assessments if item.finding_type and item.recommendation
        ]
        with self._driver.session() as session:
            session.execute_write(_write, event, clauses, obligations, mappings, findings)


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "clauseiq:" + ":".join(parts)))


def _seed(transaction, title: str, roles: list[str], sections: list[dict], controls: list[dict]) -> None:
    transaction.run("UNWIND $roles AS name MERGE (:Role {name: name})", roles=roles)
    transaction.run(
        """
        MERGE (p:Policy {id: $policyId}) SET p.title = $title
        WITH p
        UNWIND $sections AS section
        MERGE (s:PolicySection {id: section.id})
        SET s.sectionNumber = section.sectionNumber, s.heading = section.heading
        MERGE (p)-[:HAS_SECTION]->(s)
        """,
        policyId=POLICY_DOCUMENT_ID, title=title, sections=sections)
    transaction.run(
        """
        UNWIND $controls AS control
        MERGE (c:Control {id: control.id})
        SET c.name = control.name, c.frequency = control.frequency
        WITH c, control
        OPTIONAL MATCH (c)-[owned:OWNED_BY]->(:Role)
        DELETE owned
        WITH DISTINCT c, control
        OPTIONAL MATCH (r:Role {name: control.ownerRole})
        FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END | MERGE (c)-[:OWNED_BY]->(r))
        WITH c, control
        OPTIONAL MATCH (:Policy {id: $policyId})-[:HAS_SECTION]->(s:PolicySection {sectionNumber: control.policySection})
        FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END | MERGE (c)-[:IMPLEMENTS]->(s))
        """,
        policyId=POLICY_DOCUMENT_ID, controls=controls)


def _write(transaction, event: IngestionEvent, clauses: list[dict], obligations: list[dict],
           mappings: list[dict], findings: list[dict]) -> None:
    # Clear what an earlier attempt wrote for this version, so a retry cannot leave stale nodes.
    transaction.run(
        """
        MATCH (c:Clause {documentVersionId: $versionId})
        OPTIONAL MATCH (c)-[:CREATES]->(o:Obligation)
        OPTIONAL MATCH (o)-[:HAS_GAP]->(f:Finding)
        OPTIONAL MATCH (f)-[:RESOLVED_BY]->(r:Recommendation)
        DETACH DELETE r, f, o, c
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
            o.confidence = obligation.confidence, o.coverageStatus = obligation.coverageStatus,
            o.documentId = $documentId, o.documentVersionId = $versionId
        MERGE (c)-[:CREATES]->(o)
        """,
        documentId=event.document_id, versionId=event.document_version_id, obligations=obligations,
    )
    transaction.run(
        """
        UNWIND $mappings AS mapping
        MATCH (o:Obligation {id: mapping.obligationId})
        FOREACH (sectionId IN mapping.sections |
            MERGE (s:PolicySection {id: sectionId}) MERGE (o)-[:MAPS_TO]->(s))
        FOREACH (controlId IN mapping.controls |
            MERGE (c:Control {id: controlId}) MERGE (o)-[:SATISFIED_BY]->(c))
        """,
        mappings=mappings,
    )
    transaction.run(
        """
        UNWIND $findings AS finding
        MATCH (o:Obligation {id: finding.obligationId})
        MERGE (f:Finding {id: finding.id})
        SET f.findingType = finding.findingType, f.coverageStatus = finding.coverageStatus,
            f.severity = finding.severity, f.title = finding.title, f.documentVersionId = $versionId
        MERGE (o)-[:HAS_GAP]->(f)
        MERGE (r:Recommendation {id: finding.recommendationId})
        SET r.recommendedAction = finding.recommendedAction
        MERGE (f)-[:RESOLVED_BY]->(r)
        MERGE (role:Role {name: finding.assignedRole})
        MERGE (r)-[:ASSIGNED_TO]->(role)
        """,
        versionId=event.document_version_id, findings=findings,
    )


def build_graph_store(settings: Settings) -> GraphStore:
    return Neo4jStore(settings) if settings.neo4j_uri else NoGraphStore()
