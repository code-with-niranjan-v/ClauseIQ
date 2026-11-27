from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.embeddings import HashEmbedder
from app.system_assessment import (Artifact, AssessmentInputError, CircularObligation, SystemAssessor,
                                   improvement_plan, select_obligations)
from tests.conftest import make_pdf
from tests.fakes import ScriptedChatModel

EMBEDDER = HashEmbedder(256)
ROLES = ["Compliance Officer", "Data Protection Officer", "Head of Operations"]


def obligation(identifier, summary, regulator="RBI"):
    return CircularObligation(
        obligation_id=identifier, summary=summary, required_action=summary, deadline=None,
        embedding=EMBEDDER.embed([summary])[0], document_title=f"Circular {identifier}", regulator=regulator,
        source_url="https://www.rbi.org.in/c.pdf", quoted_text=summary, page_number=1, clause_number="4")


RETENTION = obligation("o1", "Audit logs must be retained for five years")
RETENTION_COPY = obligation("o2", "Audit logs must be retained for five years")      # same rule, another circular
COMPLAINTS = obligation("o3", "Customer complaints must be resolved within 30 days")
INSURANCE = obligation("o4", "Insurers must file the actuarial report for policy liabilities", "IRDAI")


class Source:
    def __init__(self, obligations):
        self.items = obligations

    def circular_obligations(self):
        return self.items

    def roles(self):
        return ROLES


def png() -> bytes:
    with BytesIO() as buffer:
        Image.new("RGB", (40, 30), "white").save(buffer, format="PNG")
        return buffer.getvalue()


def judge(prompt):
    if "actuarial" in prompt:
        return {"applicable": False, "status": "UNVERIFIED", "title": "Not applicable", "evidenceIds": [],
                "systemQuote": None, "explanation": "Insurance only.", "improvement": "", "ownerRole": "x",
                "effort": "LOW", "confidence": 0.9}
    if "Audit logs" in prompt:
        return {"applicable": True, "status": "CONFLICT", "title": "Audit log retention too short",
                "evidenceIds": ["F1", "F9"], "systemQuote": "audit logs are retained for 90 days",
                "explanation": "The design keeps logs for 90 days.", "improvement": "Retain audit logs for five years.",
                "ownerRole": "head of operations", "effort": "MEDIUM", "confidence": 0.8}
    return {"applicable": True, "status": "MEETS", "title": "Complaints resolved in time", "evidenceIds": [],
            "systemQuote": None, "explanation": "Looks fine.", "improvement": "Nothing", "ownerRole": "Wizard",
            "effort": "LOW", "confidence": 0.7}


def diagram(prompt):
    assert isinstance(prompt, list) and prompt[1]["image_url"]["url"].startswith("data:image/png;base64,")
    return {"summary": "Core banking with a log store.",
            "facts": ["The log store keeps audit logs for 90 days.", "Complaints are resolved within 30 days."]}


def assessor(obligations, **options):
    model = ScriptedChatModel({"_Judgement": judge, "_DiagramFacts": diagram})
    return SystemAssessor(Source(obligations), EMBEDDER, model, min_similarity=0.1, **options), model


def sre_pdf():
    return make_pdf([["NeoPay system requirements", "7. Logging",
                      "7.1 Application and audit logs are retained for 90 days in the log store.",
                      "8. Complaints", "8.1 Customer complaints are resolved within 30 days."]])


def test_compares_text_and_diagram_evidence_with_obligations():
    bot, model = assessor([RETENTION, RETENTION_COPY, COMPLAINTS, INSURANCE])
    artifacts = [Artifact("SRE", "sre.pdf", "application/pdf", sre_pdf()),
                 Artifact("ARCHITECTURE", "arch.png", "image/png", png())]

    result = bot.run(artifacts)

    assert [item.method for item in artifacts] == ["TEXT", "VISION"]
    assert any(fact.kind == "ARCHITECTURE" and "90 days" in fact.content for fact in result.facts)
    # The duplicate of the retention rule is compared once.
    # o1, o3 and the insurance rule are compared; the duplicate o2 is not. Insurance does not apply.
    assert result.compared == 3 and result.not_applicable == 1
    by_id = {item.obligation.obligation_id: item for item in result.findings}
    assert "o2" not in by_id
    retention = by_id["o1"]
    assert (retention.status, retention.severity, retention.owner_role) == ("CONFLICT", "HIGH", "Head of Operations")
    assert retention.system_quote is None or retention.system_quote in retention.evidence[0].content
    # A MEETS with no cited evidence is downgraded, and the invented role falls back.
    complaints = by_id["o3"]
    assert (complaints.status, complaints.severity, complaints.owner_role) == ("UNVERIFIED", "LOW", "Compliance Officer")
    assert sum(1 for name, _ in model.calls if name == "_DiagramFacts") == 1


def test_skips_obligations_for_other_businesses():
    bot, _ = assessor([INSURANCE])
    result = bot.run([Artifact("SRE", "sre.pdf", "application/pdf",
                               make_pdf([["The actuarial report for policy liabilities is not produced by NeoPay."] * 3]))])

    assert result.compared == 1 and result.not_applicable == 1 and result.findings == []


def test_requires_ingested_obligations():
    bot, _ = assessor([])
    with pytest.raises(AssessmentInputError, match="Ingest circulars first"):
        bot.run([Artifact("SRE", "sre.pdf", "application/pdf", sre_pdf())])


def test_selection_respects_threshold_and_limit():
    from app.system_assessment import extract_facts
    facts = extract_facts(Artifact("SRE", "sre.pdf", "application/pdf", sre_pdf()), None)
    for fact, vector in zip(facts, EMBEDDER.embed([fact.content for fact in facts])):
        fact.embedding = vector

    assert len(select_obligations(facts, [RETENTION, COMPLAINTS], min_similarity=0.1, limit=1)) == 1
    assert select_obligations(facts, [INSURANCE], min_similarity=0.99, limit=5) == []


def test_plan_groups_open_findings_by_severity():
    def item(identifier, severity, effort):
        return {"id": identifier, "title": identifier, "improvement": "Fix", "ownerRole": "Compliance Officer",
                "effort": effort, "status": "GAP", "severity": severity, "obligation": {"circular": {"title": "C"}}}

    plan = improvement_plan([item("b", "HIGH", "HIGH"), item("a", "HIGH", "LOW"), item("c", "LOW", "LOW")])

    assert [(phase["phase"], [entry["findingId"] for entry in phase["items"]]) for phase in plan] == [
        ("Immediate", ["a", "b"]), ("Verify", ["c"])]


def test_upload_endpoint_validates_files(monkeypatch):
    submitted = []

    class Store:
        def create(self, name, artifacts):
            submitted.append((name, [(item.kind, item.content_type) for item in artifacts]))
            return "00000000-0000-0000-0000-000000000001"

    monkeypatch.setattr(main, "get_system_store", lambda: Store())
    monkeypatch.setattr(main._assessments, "submit", lambda *args: None)
    client = TestClient(main.app)

    assert client.post("/system-assessments", data={"name": "x"}).status_code == 400
    bad = client.post("/system-assessments", files={"er": ("er.txt", b"hello", "text/plain")})
    assert bad.status_code == 400 and "PDF, PNG" in bad.json()["detail"]
    ok = client.post("/system-assessments", data={"name": "  NeoPay  "},
                     files={"sre": ("sre.pdf", sre_pdf(), "application/pdf"), "er": ("er.png", png(), "image/png")})
    assert ok.status_code == 202 and ok.json()["status"] == "QUEUED"
    assert submitted == [("NeoPay", [("SRE", "application/pdf"), ("ER", "image/png")])]


def test_selection_spreads_slots_and_drops_reworded_duplicates():
    def fact(text):
        from app.system_assessment import SystemFact
        return SystemFact("f", "a", "SRE", "sre.pdf", 1, text, EMBEDDER.embed([text])[0])

    disclose = obligation("d1", "Penal charges shall be disclosed to customers in the loan agreement")
    reworded = obligation("d2", "Penal charges must be disclosed by regulated entities to customers in the loan agreement")
    reworded.document_title = "Another circular"
    rules = ["Penal charges cannot be capitalised into principal", "Board must approve the penal charges policy",
             "Reminders must state applicable penal charges", "Penal charges must not be discriminatory",
             "Penal interest cannot be added to the rate", "Website must publish penal charges"]
    same_circular = [obligation(f"p{index}", text) for index, text in enumerate(rules)]
    for item in same_circular:
        item.document_title = "Penal charges circular"
    facts = [fact("Penal charges are not disclosed to customers in the loan agreement")]

    chosen = [item.obligation_id for item, _ in
              select_obligations(facts, [disclose, reworded, *same_circular], min_similarity=0.0, limit=12, per_fact=20)]

    assert ("d1" in chosen) != ("d2" in chosen)
    assert sum(1 for item in chosen if item.startswith("p")) == 3   # max(3, 12 // 4) per circular
