import re
import subprocess
import uuid
from io import BytesIO

import pdfplumber

from app.models import Chunk, Page

# "4.", "4.2", "4.2.1)", "Clause 4.2", "Section 3", "Para 7", "(a)", "(iv)"
_CLAUSE = re.compile(
    r"^[ \t]*(?:"
    r"(?:clause|section|para(?:graph)?|article)[ \t]+(?P<named>\d{1,3}(?:\.\d{1,3}){0,4})[.):]?"
    r"|(?P<dotted>\d{1,3}(?:\.\d{1,3}){1,4})[.):]?"
    r"|(?P<plain>\d{1,3})[.)]"  # a bare integer needs "." or ")" so wrapped lines like "15 days" do not match
    r"|(?P<item>\([a-z]{1,4}\)|\(\d{1,3}\))"
    r")[ \t]+(?=\S)",
    re.IGNORECASE | re.MULTILINE,
)


def _number(match: re.Match) -> str:
    return next(value for value in match.groups() if value)


_SENTENCE_END = re.compile(r"(?<=[.;:])\s+")


class PdfError(ValueError):
    """The PDF cannot be parsed or contains no extractable text."""


def _recognize_page(page) -> str:
    # Keep large pages within a bounded raster size.
    resolution = min(300, 72 * 4000 / max(page.width, page.height))
    with BytesIO() as image:
        page.to_image(resolution=resolution).original.save(image, format="PNG")
        try:
            result = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", "eng+hin", "--dpi", str(max(1, round(resolution)))],
                input=image.getvalue(), capture_output=True, check=True, timeout=60,
            )
        except FileNotFoundError as error:
            raise PdfError("OCR requires Tesseract with English and Hindi language data.") from error
        except subprocess.TimeoutExpired as error:
            raise PdfError(f"OCR timed out on page {page.page_number}.") from error
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode("utf-8", errors="replace").strip()
            raise PdfError(f"OCR failed on page {page.page_number}: {detail}") from error
    return result.stdout.decode("utf-8").strip()


def extract_pages(pdf_bytes: bytes) -> list[Page]:
    """Extract native text, using OCR for pages with no text layer."""
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                ocr = not text.strip()
                if ocr:
                    text = _recognize_page(page)
                pages.append(Page(page_number=page.page_number, text=text, ocr=ocr))
    except PdfError:
        raise
    except Exception as error:  # pdfminer raises several unrelated exception types
        raise PdfError(f"Could not read the PDF: {error}") from error
    if not any(page.text.strip() for page in pages):
        raise PdfError("No readable text was found in the PDF, including after OCR.")
    return pages


def extract_pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join(page.text for page in extract_pages(pdf_bytes))


def _chunk_id(version_id: str, page_number: int, start: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"clauseiq:chunk:{version_id}:{page_number}:{start}"))


def _heading(first_line: str, number: str | None) -> str | None:
    """A short first line without a sentence ending is treated as the clause heading."""
    line = first_line.strip()
    if number and line.lower().startswith(("clause", "section", "para", "article")):
        line = line.split(None, 1)[1] if " " in line else ""
    if number and line.startswith(number):
        line = line[len(number):].lstrip(".): \t")
    if 3 <= len(line) <= 90 and not line.endswith((".", ";", ",")):
        return line
    return None


def _split_long(text: str, start: int, max_chars: int) -> list[tuple[int, int]]:
    """Split [start, start+len(text)) into spans of at most max_chars, at sentence ends where possible."""
    spans: list[tuple[int, int]] = []
    position = 0
    while len(text) - position > max_chars:
        window = text[position:position + max_chars]
        breaks = [match.end() for match in _SENTENCE_END.finditer(window)]
        cut = breaks[-1] if breaks and breaks[-1] > max_chars // 3 else max_chars
        spans.append((start + position, start + position + cut))
        position += cut
    spans.append((start + position, start + len(text)))
    return spans


def chunk_pages(pages: list[Page], document_id: str, version_id: str, max_chars: int = 1500) -> list[Chunk]:
    """Split each page at detected clause numbers.

    Chunks never cross a page so every chunk has exactly one page number, and
    `content == page.text[start_offset:end_offset]` always holds. Text before the
    first clause on a page inherits the clause that was open on the previous page.
    """
    chunks: list[Chunk] = []
    open_clause: str | None = None
    open_heading: str | None = None
    for page in pages:
        text = page.text
        if not text.strip():
            continue
        starts = [(match.start(), _number(match)) for match in _CLAUSE.finditer(text)]
        segments: list[tuple[int, int, str | None, str | None]] = []
        first = starts[0][0] if starts else len(text)
        if text[:first].strip():
            segments.append((0, first, open_clause, open_heading))
        for index, (start, number) in enumerate(starts):
            end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
            heading = _heading(text[start:end].split("\n", 1)[0], number)
            # Sub-items such as "(a)" stay under the heading of their parent clause.
            if heading is None and number.startswith("("):
                heading = open_heading
            segments.append((start, end, number, heading))
            open_clause, open_heading = number, heading
        for start, end, number, heading in segments:
            for span_start, span_end in _split_long(text[start:end], start, max_chars):
                # Trim surrounding whitespace but keep offsets exact.
                content = text[span_start:span_end]
                span_start += len(content) - len(content.lstrip())
                span_end -= len(content) - len(content.rstrip())
                if span_end <= span_start:
                    continue
                chunks.append(Chunk(
                    id=_chunk_id(version_id, page.page_number, span_start),
                    document_id=document_id,
                    document_version_id=version_id,
                    page_number=page.page_number,
                    clause_number=number,
                    heading=heading,
                    content=text[span_start:span_end],
                    start_offset=span_start,
                    end_offset=span_end,
                ))
    return chunks
