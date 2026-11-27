from fastapi.testclient import TestClient

from app import lineage, main
from app.data_scan import Column, classify, parse_targets, scan
from app.embeddings import HashEmbedder
from app.extraction import _value
from app.quality import _duplicates, flags
from app.reports import posture_report, system_report, to_docx, to_pdf  # noqa: F401  (posture needs a database)

# ---------------------------------------------------------------- lineage


def test_normalize_matches_the_same_reference_written_differently():
    assert lineage.normalize("IRDAI/INT/GDL/MISC/004/ 01/2020") == lineage.normalize("IRDAI/INT/GDL/Misc/4/1/2020")
    assert lineage.normalize("RBI/2026-2027/305") == lineage.normalize("RBI/2026-27/305")


def test_own_identifiers_come_from_the_header():
    pages = [(1, "Ref: IRDAI/F&I/CIR/MISC/142/11/2026 Date: 02.11.2026\nMaster Circular on Registration ...\n"
                 + "x" * 800 + " see IRDAI/F&I/CIR/MISC/45/4/2026 later")]
    assert lineage.own_identifiers(pages) == {"IRDAI/F&I/CIR/MISC/142/11/2026"}


def test_a_number_in_the_subject_line_is_cited_not_owned():
    # The real IRDAI notice: its subject line names the guidelines it repeals.
    page = ("Circular No.: IRDAI/INT/CIR/MISC/122/9/2026 22nd September, 2026\nTo, All Insurance Intermediaries\n"
            "Subject: Repeal of the 'Guidelines on repatriation of dividends' (IRDAI/INT/GDL/MISC/004/\n"
            "01/2020 dated 03.01.2020)\n3. Accordingly, the Guidelines issued vide Ref. No. IRDAI/INT/GDL/MISC/004/\n"
            "01/2020 dated 03.01.2020 are hereby repealed with effect from 30.07.2026.")
    own = lineage.own_identifiers([(1, page)])
    assert own == {"IRDAI/INT/CIR/MISC/122/9/2026"}
    assert [(item.relation, item.normalized) for item in lineage.detect([(1, page)], own)] == [
        ("WITHDRAWS", lineage.normalize("IRDAI/INT/GDL/MISC/4/1/2020"))]


def test_detects_a_repeal_split_across_a_line_wrap():
    text = ("3. Accordingly, the Guidelines on repatriation of dividends by insurance intermediaries issued vide "
            "Ref. No. IRDAI/INT/GDL/MISC/004/\n01/2020 dated 03.01.2020 are hereby repealed with effect from 30.07.2026.")
    [citation] = lineage.detect([(2, text)], own=set())
    assert citation.relation == "WITHDRAWS"
    assert citation.normalized == lineage.normalize("IRDAI/INT/GDL/MISC/4/1/2020")
    assert citation.page_number == 2 and "hereby repealed" in citation.evidence


def test_a_list_of_repealed_circulars_applies_to_each_entry():
    text = ("Schedule I - List of Repealed Circulars\nThe following Circulars shall stand repealed consequent to the "
            "issue of this Master Circular:\n1. IRDAI/F&I/CIR/MISC/45/4/2026 dated 10.04.2026\n"
            "2. IRDAI/F&I/CIR/MISC/72/5/2026 dated 20.05.2026")
    relations = {item.normalized: item.relation for item in lineage.detect([(30, text)], own={"IRDAI/F&I/CIR/MISC/142/11/2026"})}
    assert relations == {lineage.normalize("IRDAI/F&I/CIR/MISC/45/4/2026"): "WITHDRAWS",
                         lineage.normalize("IRDAI/F&I/CIR/MISC/72/5/2026"): "WITHDRAWS"}


def test_strongest_relation_wins_and_own_numbers_are_ignored():
    text = ("Please refer to our circular DoR.RET.REC.200/12.01.001/2025-26 dated 1 May 2025. "
            "In supersession of circular DoR.RET.REC.200/12.01.001/2025-26, banks shall maintain CRR at 3%. "
            "This circular RBI/2026-27/310 is issued under Section 42.")
    citations = lineage.detect([(1, text)], own={"RBI/2026-27/310"})
    assert [(item.relation, item.identifier) for item in citations] == [
        ("SUPERSEDES", "DoR.RET.REC.200/12.01.001/2025-26")]


def test_diff_pairs_modified_new_and_removed_obligations():
    embed = HashEmbedder(128).embed
    old = [{"id": "a", "summary": "Banks must report frauds to RBI within 14 days", "quotedText": "q", "pageNumber": 1,
            "lifecycleStatus": "ACTIVE"},
           {"id": "b", "summary": "Banks must appoint a nodal officer for fraud", "quotedText": "q", "pageNumber": 2,
            "lifecycleStatus": "ACTIVE"}]
    new = [{"id": "c", "summary": "Banks must report frauds to RBI within 7 days", "quotedText": "q", "pageNumber": 1,
            "lifecycleStatus": "ACTIVE"},
           {"id": "d", "summary": "Banks must publish an annual cyber security statement", "quotedText": "q",
            "pageNumber": 3, "lifecycleStatus": "ACTIVE"}]
    for item in old + new:
        item["embedding"] = embed([item["summary"]])[0]

    changes = {item["change"]: item for item in lineage.diff_obligations(old, new, match_threshold=0.7)}
    assert changes["MODIFIED"]["before"]["id"] == "a" and changes["MODIFIED"]["after"]["id"] == "c"
    assert changes["NEW"]["after"]["id"] == "d" and changes["REMOVED"]["before"]["id"] == "b"


# ---------------------------------------------------------------- data scan


def column(name, data_type="text", comment=""):
    return Column("public", "customers", name, data_type, comment)


def test_rules_classify_by_the_most_specific_match():
    aadhaar = classify(column("aadhaar_number", "character varying(12)", "plain text, unmasked"))
    assert (aadhaar.classification, aadhaar.sensitivity, aadhaar.protected) == ("GOVERNMENT_IDENTIFIER", "HIGH", False)
    assert "unprotected" in aadhaar.reason
    assert classify(column("pin_code")).classification == "ADDRESS_LOCATION"    # not a PIN secret
    assert classify(column("mpin")).classification == "AUTHENTICATION_SECRET"
    hashed = classify(column("password_hash"))
    assert (hashed.classification, hashed.protected, hashed.sensitivity) == ("AUTHENTICATION_SECRET", True, "MEDIUM")
    assert classify(column("accountNumber")).classification == "FINANCIAL_ACCOUNT"
    assert classify(column("file_name")) is None and classify(column("created_at", "timestamp")) is None
    assert classify(column("notes", comment="Customer email address")).classification == "CONTACT"


def test_ai_is_asked_only_about_ambiguous_text_columns():
    class Model:
        asked = []

        def with_structured_output(self, schema):
            outer = self

            class Bound:
                def invoke(self, messages):
                    outer.asked.append(messages[-1][1])
                    return schema.model_validate({"fields": [
                        {"ref": "public.customers.kyc_ref_text", "classification": "GOVERNMENT_IDENTIFIER",
                         "confidence": 0.7, "reason": "Looks like a KYC document number"},
                        {"ref": "public.customers.invented", "classification": "CONTACT", "confidence": 0.9,
                         "reason": "x"}]})
            return Bound()

    model = Model()
    results, used_ai = scan([column("email"), column("kyc_ref_text"), column("status"), column("id", "uuid")], model)
    assert used_ai
    assert "kyc_ref_text" in model.asked[0] and "email" not in model.asked[0] and "status" not in model.asked[0]
    by_name = {item.column.name: item for item in results}
    assert set(by_name) == {"email", "kyc_ref_text"} and by_name["kyc_ref_text"].method == "AI"
    assert by_name["kyc_ref_text"].confidence <= 0.8


def test_scan_targets_come_only_from_configuration():
    assert parse_targets("neopay=postgresql://u:p@db:5432/neopay; bad=http://evil; =postgresql://x") == {
        "neopay": "postgresql://u:p@db:5432/neopay"}
    main.settings.scan_targets = ""
    client = TestClient(main.app)
    assert client.get("/data-scans/targets").json() == []
    assert client.post("/data-scans", json={"target": "postgresql://attacker"}).status_code == 404


# ---------------------------------------------------------------- quality, extraction


def test_null_words_from_the_model_become_no_value():
    assert _value("null") is None and _value(" Not specified ") is None and _value(None) is None
    assert _value(" within 30 days ") == "within 30 days"


def test_quality_flags():
    assert _duplicates(["Banks must report frauds within 7 days", "Banks must report frauds within 7 days.",
                        "Banks must appoint a nodal officer"]) == 1
    item = {"status": "COMPLETED", "eventStatus": "COMPLETED", "pages": 4, "obligations": 10, "rejectionRate": 0.5,
            "lowConfidenceShare": 0.1, "duplicateShare": 0.3, "ocrPages": 2}
    assert flags(item) == ["Many quotes failed citation checks", "Repeated obligations", "OCR used"]


# ---------------------------------------------------------------- reports


ASSESSMENT = {
    "name": "NeoPay", "stats": {"compared": 2, "open": 1, "meets": 1, "notApplicable": 0, "facts": 5},
    "artifacts": [{"kind": "SRE", "filename": "sre.pdf", "method": "TEXT", "factCount": 5}],
    "plan": [{"phase": "Immediate", "window": "0–30 days", "items": [
        {"title": "Notify holders", "improvement": "Send an SMS when a hold is placed.", "ownerRole": "Head of Ops",
         "effort": "LOW", "circular": {"regulator": "RBI", "title": "Debit holds <directions> & more"}}]}],
    "findings": [{"severity": "HIGH", "status": "GAP", "title": "Notify holders", "systemQuote": "not notified",
                  "evidence": [], "obligation": {"summary": "Notify the account holder", "circular": {"regulator": "RBI"}}},
                 {"severity": None, "status": "MEETS", "title": "Nodal officer", "systemQuote": None,
                  "evidence": [{"content": "Head of Fraud Risk is the Nodal Officer"}],
                  "obligation": {"summary": "Designate a nodal officer", "circular": {"regulator": "RBI"}}}],
}


def test_reports_render_as_pdf_and_word():
    report = system_report(ASSESSMENT, "Meena (Reviewer)")
    pdf = to_pdf(report)
    assert pdf.startswith(b"%PDF-") and len(pdf) > 2000
    docx = to_docx(report)
    assert docx[:2] == b"PK"     # a Word document is a zip package
    from io import BytesIO

    from docx import Document
    text = "\n".join(p.text for p in Document(BytesIO(docx)).paragraphs)
    cells = "\n".join(c.text for t in Document(BytesIO(docx)).tables for row in t.rows for c in row.cells)
    assert "System assessment: NeoPay" in text and "Meena (Reviewer)" in text
    assert "Debit holds <directions> & more" in cells    # escaped for the PDF, verbatim in Word


def test_report_format_must_be_pdf_or_word():
    assert TestClient(main.app).get("/reports/posture.exe").status_code == 404
