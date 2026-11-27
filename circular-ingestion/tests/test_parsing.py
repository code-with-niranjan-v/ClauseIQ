from io import BytesIO
from shutil import which

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.parsing import PdfError, chunk_pages, extract_pages
from app.models import Page


def test_pages_are_extracted_with_page_numbers(sample_pdf):
    pages = extract_pages(sample_pdf)

    assert [page.page_number for page in pages] == [1, 2]
    assert "Audit logs must be retained" in pages[0].text
    assert "Incident reporting" in pages[1].text


def test_chunks_keep_exact_text_offsets_and_clause_numbers(sample_pdf):
    pages = extract_pages(sample_pdf)
    chunks = chunk_pages(pages, "doc", "version")
    text = {page.page_number: page.text for page in pages}

    for chunk in chunks:
        assert chunk.content == text[chunk.page_number][chunk.start_offset:chunk.end_offset]
    numbers = [(chunk.page_number, chunk.clause_number) for chunk in chunks]
    assert (1, "4.1") in numbers and (1, "4.2") in numbers
    assert (2, "5.1") in numbers and (2, "(a)") in numbers
    by_number = {chunk.clause_number: chunk for chunk in chunks}
    assert by_number["4"].heading == "Audit logging"
    assert by_number[None].page_number == 1  # title block before the first clause


def test_wrapped_line_starting_with_a_number_is_not_a_clause():
    page = Page(page_number=1, text="3. Reporting\nEntities shall report within\n15 days of the event.")

    chunks = chunk_pages([page], "doc", "version")

    assert [chunk.clause_number for chunk in chunks] == ["3"]


def test_text_before_first_clause_inherits_clause_from_previous_page():
    pages = [Page(page_number=1, text="7.1 Entities shall keep records of every"),
             Page(page_number=2, text="transaction for ten years.\n7.2 Records must be legible.")]

    chunks = chunk_pages(pages, "doc", "version")

    assert [(chunk.page_number, chunk.clause_number) for chunk in chunks] == [(1, "7.1"), (2, "7.1"), (2, "7.2")]


def test_long_clause_is_split_without_losing_text():
    body = "1. " + " ".join(f"Sentence number {index} shall apply." for index in range(200))

    chunks = chunk_pages([Page(page_number=1, text=body)], "doc", "version", max_chars=400)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 400 for chunk in chunks)
    assert all(chunk.clause_number == "1" for chunk in chunks)
    assert "".join(chunk.content.replace(" ", "") for chunk in chunks) == body.replace(" ", "")


def test_unreadable_pdf_raises():
    with pytest.raises(PdfError):
        extract_pages(b"this is not a pdf")


@pytest.mark.skipif(which("tesseract") is None, reason="Tesseract is not installed")
def test_ocr_extracts_text_from_an_image_only_page():
    with Image.new("RGB", (1600, 500), "white") as image, BytesIO() as pdf:
        ImageDraw.Draw(image).text((80, 160), "Banks shall retain audit records.",
                                  font=ImageFont.load_default(size=64), fill="black")
        image.save(pdf, format="PDF", resolution=150)
        pages = extract_pages(pdf.getvalue())

    assert [page.page_number for page in pages] == [1]
    assert "Banks shall retain audit records." in pages[0].text
