from app.citations import Candidate, locate_quote, validate
from app.models import Page
from app.parsing import chunk_pages

TEXT = "4.1 Regulated entities shall maintain audit logs for all\nsystems that process regulated information."
PAGES = [Page(page_number=1, text=TEXT)]
CHUNKS = chunk_pages(PAGES, "doc", "version")


def candidate(quote: str, page: int = 1) -> Candidate:
    return Candidate(page_number=page, quoted_text=quote, summary="Keep audit logs", required_action="Keep logs")


def test_quote_matches_across_a_line_wrap_and_returns_the_original_span():
    span = locate_quote(TEXT, "audit logs for all systems that process")

    assert span is not None
    assert TEXT[span[0]:span[1]] == "audit logs for all\nsystems that process"


def test_valid_quote_is_accepted_with_clause_number_from_the_chunk():
    accepted, rejected = validate([candidate("shall maintain audit logs for all systems")], PAGES, CHUNKS, "version")

    assert rejected == []
    assert accepted[0].citation.clause_number == "4.1"
    assert accepted[0].citation.quoted_text == "shall maintain audit logs for all\nsystems"
    assert accepted[0].chunk_id == CHUNKS[0].id


def test_invented_quote_wrong_page_and_missing_quote_are_rejected():
    accepted, rejected = validate([
        candidate("Regulated entities shall encrypt all audit logs at rest."),
        candidate("shall maintain audit logs for all systems", page=9),
        candidate(""),
    ], PAGES, CHUNKS, "version")

    assert accepted == []
    assert [item.reason for item in rejected] == [
        "QUOTE_NOT_ON_PAGE", "PAGE_NOT_FOUND", "QUOTE_MISSING_OR_TOO_SHORT"]


def test_duplicate_quotes_produce_one_obligation():
    quote = "shall maintain audit logs for all systems"

    accepted, _ = validate([candidate(quote), candidate(quote)], PAGES, CHUNKS, "version")

    assert len(accepted) == 1
