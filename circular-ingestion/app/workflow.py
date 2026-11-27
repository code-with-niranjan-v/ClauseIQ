import hashlib
import logging
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app import citations, parsing
from app.citations import Candidate
from app.db import Repository
from app.embeddings import Embedder
from app.extraction import Extractor
from app.graph_store import GraphStore
from app.models import Chunk, IngestionEvent, IngestionResult, Obligation, Page, RejectedObligation
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


class State(TypedDict, total=False):
    event: IngestionEvent
    pdf: bytes
    pages: list[Page]
    chunks: list[Chunk]
    candidates: list[Candidate]
    obligations: list[Obligation]
    rejected: list[RejectedObligation]
    result: IngestionResult


def build_workflow(deps: Dependencies):
    """Phase 2 graph: load -> parse -> clauses -> obligations -> citations -> index -> persist.

    The Day 2 nodes from PLAN.md (retrieve_internal_evidence through
    await_human_review) attach after persist_results.
    """

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

    def persist_results(state: State) -> State:
        event = state["event"]
        result = IngestionResult(
            document_id=event.document_id, document_version_id=event.document_version_id,
            page_count=len(state["pages"]), chunks=state["chunks"],
            obligations=state["obligations"], rejected=state["rejected"])
        # Neo4j first: its writes are idempotent, and PostgreSQL marks the event
        # completed in the same transaction as the results. A failure in either
        # store leaves the event retryable with nothing reported as completed.
        if deps.graph is not None:
            deps.graph.save(event, result)
        if deps.repository is not None:
            deps.repository.save_result(event, result)
        return {"result": result}

    nodes = [load_document, parse_pages, detect_clauses, extract_obligations,
             validate_citations, index_regulatory_content, persist_results]
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
