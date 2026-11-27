"""Writes sample-data/circulars/sample-circular.pdf. Needs reportlab (requirements-dev.txt)."""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PAGES = [
    [
        "SAMPLE REGULATORY AUTHORITY",
        "Circular SRA/2026/014: Information Security and Data Governance",
        "This is mock data for the ClauseIQ demonstration. It is not a real circular.",
        "",
        "1. Introduction",
        "This circular sets out minimum requirements for regulated entities that",
        "process customer information. It applies from the date of publication.",
        "",
        "2. Audit logging",
        "2.1 Regulated entities shall maintain audit logs for all systems that process",
        "regulated information and shall review those logs at least once every quarter.",
        "2.2 Regulated entities shall retain audit logs for a period of at least five years.",
        "",
        "3. Incident reporting",
        "3.1 A regulated entity shall report any security incident that affects regulated",
        "information to the Authority within 6 hours of detection.",
    ],
    [
        "4. Third parties",
        "4.1 Regulated entities shall assess the security of each third party before",
        "sharing customer personal data with it and at least annually thereafter.",
        "",
        "5. Data localisation",
        "5.1 Regulated entities shall store all customer payment data only on systems",
        "located in India.",
        "",
        "6. General",
        "6.1 The Authority may issue further guidance on these requirements.",
    ],
]


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "sample-data" / "circulars" / "sample-circular.pdf"
    pdf = canvas.Canvas(str(target), pagesize=A4, invariant=1)
    for lines in PAGES:
        y = 800
        for line in lines:
            pdf.drawString(60, y, line)
            y -= 22
        pdf.showPage()
    pdf.save()
    print(target)


if __name__ == "__main__":
    main()
