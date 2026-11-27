"""Generate the NeoPay demo bank's SRE document, architecture diagram and ER diagram.

Kaveri Bank and NeoPay are fictional. The documents deliberately contain design gaps against the
circulars ClauseIQ ingests, and some controls that meet them. See README.md for the answer key.

Run from the repository root (needs reportlab and Pillow, both in circular-ingestion/requirements-dev.txt):
    python demo-bank/generate_artifacts.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parent.parent / "clauseiq-frontend" / "public" / "demo-bank"

SRE = [
    ("1. Purpose and scope", [
        "1.1 This System Requirements and Engineering (SRE) document describes NeoPay, the digital banking platform "
        "of Kaveri Bank Limited. NeoPay offers savings accounts, UPI payments and unsecured personal loans to retail "
        "customers through a mobile app and a web portal.",
        "1.2 NeoPay is available to customers aged 10 years and above. Customers aged 10 to 17 hold minor savings "
        "accounts with a daily transaction limit of Rs 10,000.",
    ]),
    ("2. Customer onboarding and consent", [
        "2.1 Customers are onboarded through video KYC. The full 12-digit Aadhaar number, PAN, date of birth, mobile "
        "number, email and address are stored in the customers table of the core database.",
        "2.2 Consent to process personal data is captured through a single checkbox that accepts the terms and "
        "conditions. Minor customers tick the checkbox themselves. NeoPay does not collect or verify the consent of "
        "a parent or guardian.",
        "2.3 Customers cannot withdraw consent or request deletion of their data from the app. Requests sent to "
        "customer care are handled manually.",
    ]),
    ("3. Sanctions screening", [
        "3.1 New customers are screened at onboarding against an internal watchlist maintained by the compliance team. "
        "The watchlist is refreshed once a quarter. The UNSC sanctions lists and the lists notified under the UAPA "
        "Order are not integrated into screening.",
        "3.2 Existing customers are not re-screened when the watchlist changes.",
        "3.3 Requests from customers to be removed (de-listed) from a sanctions list are e-mailed to the compliance "
        "mailbox and decided by the Compliance Officer. They are not forwarded to any external authority.",
    ]),
    ("4. Transaction monitoring and suspicious accounts", [
        "4.1 A rules engine flags accounts that may be operated as money mules, for example many small credits "
        "followed by immediate transfers out. Alerts are reviewed by the operations team once a week.",
        "4.2 When an analyst suspects fraud, the operations team places a debit hold on the account in the operations "
        "console. The account holder is not notified when a debit hold is placed or removed.",
        "4.3 A debit hold stays in place until an analyst removes it manually. There is no time limit for the review.",
        "4.4 The Head of Fraud Risk is designated as the Nodal Officer for coordination with police and law "
        "enforcement agencies and for complaints about debit holds. Contact details are published on the website.",
    ]),
    ("5. Personal loans", [
        "5.1 Overdue personal loan instalments attract penal interest of 2% per annum, which is added to the loan's "
        "rate of interest for the overdue period.",
        "5.2 Unpaid penal interest is capitalised into the outstanding principal at the end of each month.",
        "5.3 The Key Fact Statement (KFS) shown before sanction lists the rate of interest and processing fee. "
        "Penal charges are not shown in the KFS or in the loan agreement.",
        "5.4 Payment reminders sent by SMS state the amount due and the due date only.",
        "5.5 Interest rate changes are applied to existing loans from the next instalment, prospectively.",
    ]),
    ("6. Complaints", [
        "6.1 Complaints are logged in the complaints module. They are acknowledged within 48 hours and the "
        "service-level target for resolution is 45 calendar days.",
    ]),
    ("7. Data protection, hosting and third parties", [
        "7.1 The core database runs in the bank's Mumbai data centre. A disaster-recovery replica is maintained in a "
        "cloud region in Singapore and receives a full copy of the database every 15 minutes.",
        "7.2 Customer mobile numbers, email addresses and transaction categories are sent daily to InsightMetrics Inc., "
        "a marketing analytics vendor in the United States. There is no data processing agreement with the vendor.",
        "7.3 NeoPay has not been audited by an independent data auditor. Data protection reviews are performed "
        "internally by the IT team.",
    ]),
    ("8. Security, logging and retention", [
        "8.1 Customers sign in with a password and an SMS one-time password. Staff sign in to the operations console "
        "with a password only.",
        "8.2 Data at rest in the core database is encrypted with AES-256. The Aadhaar number is not masked or "
        "tokenised and is visible to operations staff.",
        "8.3 Application and audit logs are retained for 90 days in the log store and then deleted.",
        "8.4 Transaction and KYC records are retained for 10 years after the account is closed.",
    ]),
]


def sre_pdf(path: Path) -> None:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10.5, leading=14, spaceAfter=6)
    story = [Paragraph("Kaveri Bank Limited (fictional)", styles["Normal"]),
             Paragraph("NeoPay Digital Banking Platform", styles["Title"]),
             Paragraph("System Requirements and Engineering (SRE) Document, version 2.3", styles["Heading3"]),
             Paragraph("Classification: Internal. Demonstration document for ClauseIQ.", styles["Italic"]),
             Spacer(1, 6 * mm)]
    for heading, paragraphs in SRE:
        story.append(Paragraph(heading, styles["Heading2"]))
        story.extend(Paragraph(text, body) for text in paragraphs)
    SimpleDocTemplate(str(path), pagesize=A4, title="NeoPay SRE document", author="Kaveri Bank (fictional)",
                      leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm).build(story)


def font(size: int):
    return ImageFont.load_default(size=size)


def box(draw, xy, title, lines=(), fill="#eef3fb", outline="#2f4b7c", title_fill="#2f4b7c"):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=10, fill=fill, outline=outline, width=2)
    draw.rounded_rectangle((x1, y1, x2, y1 + 34), radius=10, fill=title_fill)
    draw.rectangle((x1, y1 + 20, x2, y1 + 34), fill=title_fill)
    draw.text((x1 + 10, y1 + 7), title, font=font(18), fill="white")
    for index, line in enumerate(lines):
        draw.text((x1 + 10, y1 + 44 + index * 22), line, font=font(15), fill="#1d2433")


def arrow(draw, start, end, label="", color="#3a3f4b", offset=(6, -20)):
    draw.line([start, end], fill=color, width=3)
    (x1, y1), (x2, y2) = start, end
    length = max(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 1)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    draw.polygon([end, (x2 - 14 * ux + 7 * uy, y2 - 14 * uy - 7 * ux), (x2 - 14 * ux - 7 * uy, y2 - 14 * uy + 7 * ux)],
                 fill=color)
    if label:
        draw.text(((x1 + x2) / 2 + offset[0], (y1 + y2) / 2 + offset[1]), label, font=font(14), fill=color)


def route(draw, points, label="", color="#3a3f4b", label_at=None):
    """An arrow along a path of right angles, so it stays clear of the boxes."""
    draw.line(points, fill=color, width=3, joint="curve")
    arrow(draw, points[-2], points[-1], color=color)
    if label:
        draw.text(label_at or points[1], label, font=font(14), fill=color)


def architecture_png(path: Path) -> None:
    image = Image.new("RGB", (1800, 1150), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 25), "NeoPay Digital Banking: Architecture (Kaveri Bank, fictional)", font=font(30), fill="#111")
    draw.text((40, 68), "Version 2.3. Red boxes are third parties outside India.", font=font(17), fill="#555")
    box(draw, (40, 130, 330, 230), "NeoPay mobile app", ["Android and iOS", "Password + SMS OTP login"])
    box(draw, (40, 270, 330, 370), "Web portal", ["Password + SMS OTP login"])
    box(draw, (40, 450, 330, 570), "Operations console", ["Staff login: password only", "Places and removes debit holds",
                                                           "Aadhaar shown unmasked"])
    box(draw, (470, 200, 760, 320), "API gateway", ["TLS 1.2", "Rate limiting"])
    services = [("Onboarding and KYC", ["Video KYC", "Single consent checkbox", "No guardian consent"]),
                ("Payments (UPI)", ["UPI switch integration"]),
                ("Personal loans", ["Penal interest 2% p.a.", "Penal interest capitalised monthly"]),
                ("Transaction monitoring", ["Mule rules; weekly alert review", "No customer notice of holds"]),
                ("Complaints", ["Resolution SLA: 45 days"])]
    for index, (title, lines) in enumerate(services):
        y = 130 + index * 150
        box(draw, (900, y, 1250, y + 125), title, lines)
        arrow(draw, (760, 260), (900, y + 60))
    box(draw, (470, 760, 760, 900), "Sanctions screening", ["Internal watchlist", "Refreshed quarterly",
                                                            "UNSC / UAPA lists not integrated"])
    route(draw, [(900, 230), (840, 230), (840, 830), (760, 830)], "screens at onboarding only",
          label_at=(848, 690))
    box(draw, (1400, 300, 1760, 450), "Core database (PostgreSQL)", ["Mumbai data centre", "AES-256 at rest",
                                                                   "Aadhaar stored in full", "KYC kept 10 years"])
    box(draw, (1400, 560, 1760, 680), "DR replica", ["Cloud region: Singapore", "Full copy every 15 minutes"],
        fill="#fdeeee", outline="#b3261e", title_fill="#b3261e")
    box(draw, (1400, 760, 1760, 900), "InsightMetrics Inc. (USA)", ["Marketing analytics vendor",
                                                                    "Receives mobile, email,", "transaction categories daily",
                                                                    "No data processing agreement"],
        fill="#fdeeee", outline="#b3261e", title_fill="#b3261e")
    box(draw, (1400, 130, 1760, 240), "Log store", ["Application and audit logs", "Retention: 90 days"])
    for index in range(5):
        arrow(draw, (1250, 190 + index * 150), (1400, 375))
    arrow(draw, (1580, 450), (1580, 560), "replication", color="#b3261e", offset=(10, -10))
    route(draw, [(1400, 435), (1330, 435), (1330, 830), (1400, 830)], "daily export", color="#b3261e",
          label_at=(1338, 715))
    arrow(draw, (330, 180), (470, 250))
    arrow(draw, (330, 320), (470, 280))
    arrow(draw, (330, 510), (900, 660), "debit holds", offset=(-60, 10))
    arrow(draw, (1250, 160), (1400, 185), "logs")
    image.save(path, optimize=True)


TABLES = [
    ("customers", (40, 130), ["customer_id  PK", "full_name", "date_of_birth", "aadhaar_number  (plain text, unmasked)",
                              "pan", "mobile", "email", "address", "is_minor", "consent_checkbox_at",
                              "guardian_consent  (no column)"]),
    ("accounts", (620, 130), ["account_id  PK", "customer_id  FK -> customers", "account_number", "ifsc", "balance",
                              "debit_hold  (boolean)", "hold_placed_at", "hold_notified_to_customer  (no column)"]),
    ("transactions", (1200, 130), ["txn_id  PK", "account_id  FK -> accounts", "amount", "counterparty_vpa",
                                   "category", "created_at", "mule_alert_flag"]),
    ("loans", (40, 600), ["loan_id  PK", "customer_id  FK -> customers", "principal", "interest_rate",
                          "penal_interest_rate  (2% p.a., added to rate)", "capitalised_penal_amount", "kfs_version"]),
    ("complaints", (620, 600), ["complaint_id  PK", "customer_id  FK -> customers", "category", "opened_at",
                                "acknowledged_at", "resolved_at", "sla_days  (default 45)"]),
    ("audit_logs", (1200, 600), ["log_id  PK", "actor", "action", "entity", "created_at",
                                 "retention  (deleted after 90 days)"]),
]


def er_png(path: Path) -> None:
    image = Image.new("RGB", (1760, 1100), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 25), "NeoPay core database: ER diagram (Kaveri Bank, fictional)", font=font(30), fill="#111")
    draw.text((40, 68), "PostgreSQL, Mumbai. Replicated in full to the Singapore DR region.", font=font(17), fill="#555")
    for name, (x, y), fields in TABLES:
        height = 50 + 26 * len(fields)
        box(draw, (x, y, x + 520, y + height), name)
        for index, text in enumerate(fields):
            colour = "#b3261e" if "(" in text and ("plain" in text or "no column" in text or "90 days" in text
                                                   or "added" in text or "45" in text) else "#1d2433"
            draw.text((x + 12, y + 44 + index * 26), text, font=font(16), fill=colour)
    arrow(draw, (560, 250), (620, 250), "1..n")
    arrow(draw, (1140, 250), (1200, 250), "1..n")
    arrow(draw, (300, 450), (300, 600), "1..n", offset=(10, -10))
    arrow(draw, (500, 450), (760, 600), "1..n", offset=(10, -10))
    draw.text((40, 1040), "Red text: fields relevant to compliance review.", font=font(16), fill="#b3261e")
    image.save(path, optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sre_pdf(OUT / "neopay-sre.pdf")
    architecture_png(OUT / "neopay-architecture.png")
    er_png(OUT / "neopay-er-diagram.png")
    print(f"Wrote the NeoPay demo documents to {OUT}")


if __name__ == "__main__":
    main()
