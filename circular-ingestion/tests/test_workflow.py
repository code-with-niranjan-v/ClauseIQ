import pytest

from app import workflow
from app.citations import Candidate
from app.consumer import EventProcessor
from app.embeddings import HashEmbedder
from app.extraction import LlmExtractor, RuleBasedExtractor
from app.parsing import extract_pages
from tests.fakes import MemoryGraph, MemoryRepository, MemoryStore, make_event


def build(pdf, extractor=None, store=None):
    event = make_event(pdf)
    repository, graph = MemoryRepository(), MemoryGraph()
    pipeline = workflow.build_workflow(workflow.Dependencies(
        store=store or MemoryStore({(event.minio_bucket, event.minio_object_key): pdf}),
        extractor=extractor or RuleBasedExtractor(), embedder=HashEmbedder(64),
        repository=repository, graph=graph))
    return event, repository, graph, pipeline


def test_one_circular_produces_cited_obligations(sample_pdf):
    event, repository, graph, pipeline = build(sample_pdf)

    result = workflow.run(pipeline, event)

    assert result.page_count == 2
    cited = {(item.citation.page_number, item.citation.clause_number) for item in result.obligations}
    assert {(1, "4.1"), (1, "4.2"), (2, "5.1"), (2, "(a)")} <= cited
    assert (2, "5.2") not in cited  # "may consider" is not an obligation
    pages = {page.page_number: page.text for page in extract_pages(sample_pdf)}
    for item in result.obligations:
        citation = item.citation
        assert pages[citation.page_number][citation.start_offset:citation.end_offset] == citation.quoted_text
    incident = next(item for item in result.obligations if item.citation.clause_number == "5.1")
    assert incident.deadline == "within 6 hours"
    assert all(len(chunk.embedding) == 64 for chunk in result.chunks)
    assert repository.results[event.document_version_id] is result
    assert graph.saved == [result]


def test_checksum_mismatch_stops_before_anything_is_saved(sample_pdf):
    event, repository, graph, pipeline = build(sample_pdf)
    tampered = event.model_copy(update={"checksum": "0" * 64})

    with pytest.raises(workflow.ChecksumMismatch):
        workflow.run(pipeline, tampered)
    assert repository.results == {} and graph.saved == []


class FakeChatModel:
    """Stands in for a LangChain chat model with structured output."""

    def __init__(self, replies):
        self.replies = replies
        self.prompts = []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.prompts.append(messages)
        return self.schema.model_validate({"obligations": self.replies.pop(0)})


def test_llm_obligation_with_an_invented_quote_is_rejected(sample_pdf):
    real = {"summary": "Retain audit logs for five years", "requiredAction": "Retain audit logs",
            "quotedText": "Audit logs must be retained for a period of five years.", "confidence": 0.9}
    invented = {"summary": "Encrypt logs", "requiredAction": "Encrypt audit logs",
                "quotedText": "Audit logs must be encrypted with approved algorithms.", "confidence": 0.95}
    model = FakeChatModel([[real, invented], []])
    event, _, _, pipeline = build(sample_pdf, extractor=LlmExtractor(model))

    result = workflow.run(pipeline, event)

    assert [item.summary for item in result.obligations] == ["Retain audit logs for five years"]
    assert result.obligations[0].citation.clause_number == "4.2"
    assert result.obligations[0].extraction_method == "LLM"
    assert [item.reason for item in result.rejected] == ["QUOTE_NOT_ON_PAGE"]
    assert len(model.prompts) == 2 and "<page>" in model.prompts[0][1][1]


def test_duplicate_event_is_processed_once(sample_pdf):
    event, repository, graph, pipeline = build(sample_pdf)
    processor = EventProcessor(repository, pipeline, max_attempts=3, backoff_seconds=0, sleep=lambda _: None)

    assert processor.process(event) == "COMPLETED"
    assert processor.process(event) == "SKIPPED"
    assert len(graph.saved) == 1


class FlakyStore:
    def __init__(self, pdf, failures):
        self.pdf, self.failures = pdf, failures

    def get(self, bucket, key):
        if self.failures:
            self.failures -= 1
            raise ConnectionError("MinIO unavailable")
        return self.pdf


def test_failure_is_retried_then_succeeds(sample_pdf):
    event, repository, _, pipeline = build(sample_pdf, store=FlakyStore(sample_pdf, failures=2))
    processor = EventProcessor(repository, pipeline, max_attempts=3, backoff_seconds=0, sleep=lambda _: None)

    assert processor.process(event) == "COMPLETED"
    assert repository.attempts[event.event_id] == 3


def test_event_is_dead_lettered_after_the_retry_limit_with_nothing_saved():
    event, repository, graph, pipeline = build(b"not a pdf")
    processor = EventProcessor(repository, pipeline, max_attempts=3, backoff_seconds=0, sleep=lambda _: None)

    assert processor.process(event) == "DEAD_LETTERED"
    assert repository.status[event.event_id] == "DEAD_LETTERED"
    assert repository.attempts[event.event_id] == 3
    assert "PdfError" in processor.last_error
    assert repository.results == {} and graph.saved == []
