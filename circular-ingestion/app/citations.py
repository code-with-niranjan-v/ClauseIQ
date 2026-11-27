import re
import uuid

from pydantic import BaseModel

from app.models import Chunk, Citation, Obligation, Page, RejectedObligation

MIN_QUOTE_CHARS = 20
_SPACE = re.compile(r"\s+")


class Candidate(BaseModel):
    """An obligation proposed by an extractor, before its citation is checked."""

    page_number: int
    quoted_text: str
    summary: str
    required_action: str
    responsible_entity: str | None = None
    deadline: str | None = None
    applicability: str | None = None
    confidence: float = 0.5
    extraction_method: str = "RULES"


def locate_quote(page_text: str, quote: str) -> tuple[int, int] | None:
    """Find the quote on the page and return its character span.

    Matching ignores differences in whitespace, because PDF line wraps turn into
    newlines, and nothing else. The returned span indexes the original page text.
    """
    if not quote.strip():
        return None
    start = page_text.find(quote)
    if start >= 0:
        return start, start + len(quote)
    # Collapse whitespace on both sides, remembering where each kept character came from.
    kept: list[str] = []
    origin: list[int] = []
    previous_space = True
    for index, character in enumerate(page_text):
        if character.isspace():
            if not previous_space:
                kept.append(" ")
                origin.append(index)
            previous_space = True
        else:
            kept.append(character)
            origin.append(index)
            previous_space = False
    needle = _SPACE.sub(" ", quote).strip()
    position = "".join(kept).find(needle)
    if position < 0:
        return None
    return origin[position], origin[position + len(needle) - 1] + 1


def validate(candidates: list[Candidate], pages: list[Page], chunks: list[Chunk],
             version_id: str) -> tuple[list[Obligation], list[RejectedObligation]]:
    """Accept only obligations whose quote occurs on the cited page of this document version."""
    page_text = {page.page_number: page.text for page in pages}
    accepted: dict[str, Obligation] = {}
    rejected: list[RejectedObligation] = []

    def reject(candidate: Candidate, reason: str) -> None:
        rejected.append(RejectedObligation(summary=candidate.summary, quoted_text=candidate.quoted_text,
                                           page_number=candidate.page_number, reason=reason))

    for candidate in candidates:
        text = page_text.get(candidate.page_number)
        if text is None:
            reject(candidate, "PAGE_NOT_FOUND")
            continue
        if len(candidate.quoted_text.strip()) < MIN_QUOTE_CHARS:
            reject(candidate, "QUOTE_MISSING_OR_TOO_SHORT")
            continue
        span = locate_quote(text, candidate.quoted_text)
        if span is None:
            reject(candidate, "QUOTE_NOT_ON_PAGE")
            continue
        start, end = span
        chunk = next((item for item in chunks if item.page_number == candidate.page_number
                      and item.start_offset <= start < item.end_offset), None)
        if chunk is None:
            reject(candidate, "QUOTE_OUTSIDE_INDEXED_TEXT")
            continue
        obligation_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL, f"clauseiq:obligation:{version_id}:{candidate.page_number}:{start}:{end}"))
        if obligation_id in accepted:
            continue  # same quote proposed twice
        accepted[obligation_id] = Obligation(
            obligation_id=obligation_id,
            chunk_id=chunk.id,
            summary=candidate.summary.strip(),
            required_action=candidate.required_action.strip(),
            responsible_entity=candidate.responsible_entity,
            deadline=candidate.deadline,
            applicability=candidate.applicability,
            # The clause number comes from the parsed chunk, never from the model.
            citation=Citation(page_number=candidate.page_number, clause_number=chunk.clause_number,
                              quoted_text=text[start:end], start_offset=start, end_offset=end),
            confidence=min(max(candidate.confidence, 0.0), 1.0),
            extraction_method=candidate.extraction_method,
        )
    return list(accepted.values()), rejected
