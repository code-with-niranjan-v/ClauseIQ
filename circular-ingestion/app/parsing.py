from io import BytesIO

import pdfplumber


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF, page by page."""
    pages: list[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)
