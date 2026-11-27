import hashlib
import logging
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app import assessment, citations, parsing
from app.assessment import Assessor
from app.citations import Candidate
from app.db import Repository
from app.embeddings import Embedder
from app.extraction import Extractor
from app.graph_store import GraphStore
from app.knowledge import KnowledgeBase
from app.models import (Assessment, Chunk, IngestionEvent, IngestionResult, Obligation, Page,
                        RejectedObligation)
from app.storage import ObjectStore

logger = logging.getLogger(__name__)


class ChecksumMismatch(ValueError):
    """The object in MinIO is not the PDF the event describes."""


@dataclass
class Dependencies:
    store: ObjectStore
    extractor: Extractor
    embedder: Embedder
    repository: Repository | None  # None runs the pipeline without persisting (CLI, tests)
    graph: GraphStore | None
    chunk_max_chars: int = 1500
    # Day 2. Without a knowledge base and assessor the workflow stops at extraction.
    knowledge: KnowledgeBase | None = None
    assessor: Assessor | None = None
    policy_top_k: int = 4
    control_top_k: int = 3


class State(TypedDict, total=False):
    event: IngestionEvent
    pdf: bytes
    pages: list[Page]
    chunks: list[Chunk]
    candidates: list[Candidate]
    obligations: list[Obligation]
    rejected: list[RejectedObligation]
    roles: list[str]
    assessments: list[Assessment]
    result: IngestionResult
    review_status: str


def build_workflow(deps: Dependencies):
    """The LangGraph workflow from PLAN.md, one node per step, run in sequence for one document."""
    mapping = deps.knowledge is not None and deps.assessor is not None

    def load_document(state: State) -> State:
        event = state["event"]
        pdf = deps.store.get(event.minio_bucket, event.minio_object_key)
        expected = event.checksum.lower().removeprefix("sha256:").removeprefix("sha256-")
        actual = hashlib.sha256(pdf).hexdigest()
        if actual != expected:
            raise ChecksumMismatch(
                f"{event.minio_bucket}/{event.minio_object_key} has SHA-256 {actual}, the event says {expected}")
        return {"pdf": pdf}

    def parse_pages(state: State) -> State:
        return {"pages": parsing.extract_pages(state["pdf"])}

    def detect_clauses(state: State) -> State:
        event = state["event"]
        return {"chunks": parsing.chunk_pages(
            state["pages"], event.document_id, event.document_version_id, deps.chunk_max_chars)}

    def extract_obligations(state: State) -> State:
        return {"candidates": deps.extractor.extract(state["pages"], state["chunks"])}

    def validate_citations(state: State) -> State:
        accepted, rejected = citations.validate(
            state["candidates"], state["pages"], state["chunks"], state["event"].document_version_id)
        for item in rejected:
            logger.warning("Rejected obligation on page %s: %s", item.page_number, item.reason)
        return {"obligations": accepted, "rejected": rejected}

    def index_regulatory_content(state: State) -> State:
        chunks = state["chunks"]
        vectors = deps.embedder.embed([chunk.content for chunk in chunks]) if chunks else []
        return {"chunks": [chunk.model_copy(update={"embedding": vector})
                           for chunk, vector in zip(chunks, vectors, strict=True)]}

    def retrieve_internal_evidence(state: State) -> State:
        obligations = state["obligations"]
        if not mapping or not obligations:
            return {"assessments": [], "roles": []}
        vectors = deps.embedder.embed(
            [f"{item.summary}\n{item.required_action}\n{item.citation.quoted_text}" for item in obligations])
        return {
            "roles": deps.knowledge.roles(),
            "assessments": [
                Assessment(obligation_id=item.obligation_id,
                           policies=deps.knowledge.search_policies(vector, deps.policy_top_k),
                           controls=deps.knowledge.search_controls(vector, deps.control_top_k))
                for item, vector in zip(obligations, vectors, strict=True)],
        }

    def map_policies_and_controls(state: State) -> State:
        obligations = {item.obligation_id: item for item in state["obligations"]}
        return {"assessments": [
            deps.assessor.assess(obligations[item.obligation_id], item.policies, item.controls)
            for item in state["assessments"]]}

    def check_role_coverage(state: State) -> State:
        return {"assessments": [assessment.check_role_coverage(item, state["roles"])
                                for item in state["assessments"]]}

    def assess_gap(state: State) -> State:
        return {"assessments": [assessment.assess_gap(item) for item in state["assessments"]]}

    def draft_recommendation(state: State) -> State:
        obligations = {item.obligation_id: item for item in state["obligations"]}
        drafted = []
        for item in state["assessments"]:
            if item.finding_type is not None:
                item = item.model_copy(update={"recommendation": deps.assessor.draft(
                    obligations[item.obligation_id], item, state["roles"])})
            drafted.append(item)
        return {"assessments": drafted}

    def persist_results(state: State) -> State:
        event = state["event"]
        result = IngestionResult(
            document_id=event.document_id, document_version_id=event.document_version_id,
            page_count=len(state["pages"]), chunks=state["chunks"],
            obligations=state["obligations"], rejected=state["rejected"], assessments=state["assessments"])
        # Neo4j first: its writes are idempotent, and PostgreSQL marks the event
        # completed in the same transaction as the results. A failure in either
        # store leaves the event retryable with nothing reported as completed.
        if deps.graph is not None:
            deps.graph.save(event, result)
        if deps.repository is not None:
            deps.repository.save_result(event, result)
        return {"result": result}

    def await_human_review(state: State) -> State:
        # Findings are stored as PENDING_REVIEW. The accept, edit and reject steps
        # belong to the review API in the Spring backend, so the graph ends here.
        pending = sum(1 for item in state["assessments"] if item.finding_type is not None)
        logger.info("%s finding(s) await human review", pending)
        return {"review_status": "PENDING_REVIEW" if pending else "NO_FINDINGS"}

    nodes = [load_document, parse_pages, detect_clauses, extract_obligations, validate_citations,
             index_regulatory_content, retrieve_internal_evidence, map_policies_and_controls,
             check_role_coverage, assess_gap, draft_recommendation, persist_results, await_human_review]
    graph = StateGraph(State)
    for node in nodes:
        graph.add_node(node.__name__, node)
    graph.add_edge(START, nodes[0].__name__)
    for current, following in zip(nodes, nodes[1:]):
        graph.add_edge(current.__name__, following.__name__)
    graph.add_edge(nodes[-1].__name__, END)
    return graph.compile()


def run(workflow, event: IngestionEvent) -> IngestionResult:
    return workflow.invoke({"event": event})["result"]
