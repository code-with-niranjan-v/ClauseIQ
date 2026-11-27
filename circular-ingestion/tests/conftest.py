import os

# The API tests must not try to reach Kafka.
os.environ["CONSUMER_ENABLED"] = "false"

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO

PAGE_ONE = [
    "RESERVE BANK OF SAMPLE",
    "Circular on Audit Logging and Data Retention",
    "1. Introduction",
    "This circular sets out requirements for regulated entities. It replaces the",
    "guidance issued earlier and applies from the date of publication.",
    "4. Audit logging",
    "4.1 Regulated entities shall maintain audit logs for all systems that process",
    "regulated information and shall review them at least once every quarter.",
    "4.2 Audit logs must be retained for a period of five years.",
]
PAGE_TWO = [
    "5. Incident reporting",
    "5.1 A regulated entity is required to report any security incident to the",
    "regulator within 6 hours of detection.",
    "5.2 The board may consider additional reporting where it sees fit.",
    "(a) Customer data must not be stored outside approved systems.",
]


def make_pdf(pages: list[list[str]]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    for lines in pages:
        y = 800
        for line in lines:
            pdf.drawString(60, y, line)
            y -= 22
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.fixture(scope="session")
def sample_pdf() -> bytes:
    return make_pdf([PAGE_ONE, PAGE_TWO])
