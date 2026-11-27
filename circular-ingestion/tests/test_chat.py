import pytest
from fastapi.testclient import TestClient

from app import main
from app.chat import INSUFFICIENT_EVIDENCE, ApprovedSource, PolicyAssistant
from app.embeddings import HashEmbedder
from tests.fakes import ScriptedChatModel

RETENTION = ApprovedSource(
    chunk_id="p5", source_type="POLICY", section_number="5", heading="Audit logging",
    content="Audit logs are retained for five years and reviewed every quarter.", similarity=0.62)
UPDATE = ApprovedSource(
    chunk_id="u1", source_type="POLICY_UPDATE", section_number="6", heading="Incident reporting gap",
    content="Security incidents are reported to the regulator within 6 hours.", similarity=0.55,
    circular_title="Circular on Incident Reporting", regulator="RBI", source_url="https://www.rbi.org.in/c.pdf")
WEAK = ApprovedSource(chunk_id="p9", source_type="POLICY", content="Travel expenses.", similarity=0.1)


class Knowledge:
    def __init__(self, sources, failing_sync=False):
        self.sources = sources
        self.failing_sync = failing_sync
        self.synced = 0

    def sync_policy_updates(self, embedder):
        self.synced += 1
        if self.failing_sync:
            raise RuntimeError("database busy")
        return 0

    def search_approved(self, embedding, limit):
        return self.sources[:limit]


def answer(**overrides):
    reply = {"answerable": True, "domain": "Incident management", "answer": "Report within 6 hours.",
             "conditions": ["Report after detection"], "citedSourceIds": ["S2"],
             "requiresSystemApproval": False, "approvalNote": None}
    reply.update(overrides)
    return lambda prompt: reply


def assistant(sources, reply, **options):
    model = ScriptedChatModel({"_Answer": reply})
    return PolicyAssistant(Knowledge(sources, **options), HashEmbedder(64), model), model


def test_answers_with_only_the_cited_sources():
    bot, model = assistant([RETENTION, UPDATE], answer())

    result = bot.ask("  How fast must we report an incident?  ")

    assert result["status"] == "ANSWERED"
    assert result["answer"] == "Report within 6 hours."
    assert [item["id"] for item in result["citations"]] == ["u1"]
    assert result["citations"][0]["circular"] == {
        "title": "Circular on Incident Reporting", "regulator": "RBI", "sourceUrl": "https://www.rbi.org.in/c.pdf"}
    prompt = model.calls[0][1]
    assert "<question>\nHow fast must we report an incident?\n</question>" in prompt
    assert 'type="POLICY_UPDATE"' in prompt and 'circular="RBI Circular on Incident Reporting"' in prompt


def test_refuses_without_calling_the_model_when_nothing_clears_the_threshold():
    bot, model = assistant([WEAK], answer())

    result = bot.ask("Can I expense a taxi?")

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["answer"] == INSUFFICIENT_EVIDENCE and result["citations"] == []
    assert model.calls == []


@pytest.mark.parametrize("reply", [
    answer(answerable=False, answer=""),
    answer(citedSourceIds=["S7"]),           # invented id
    answer(citedSourceIds=[]),
])
def test_refuses_when_the_model_has_no_real_support(reply):
    bot, _ = assistant([RETENTION, UPDATE], reply)

    result = bot.ask("What is the policy on quantum keys?")

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["citations"] == []


def test_warns_when_system_specific_approval_is_required():
    bot, _ = assistant([RETENTION], answer(citedSourceIds=["S1"], requiresSystemApproval=True,
                                           approvalNote="Ask the CISO to approve the tool."))

    assert bot.ask("Can I keep logs in a new tool?")["warning"] == "Ask the CISO to approve the tool."


def test_still_answers_from_the_handbook_when_update_indexing_fails():
    bot, _ = assistant([RETENTION], answer(citedSourceIds=["S1"]), failing_sync=True)

    assert bot.ask("How long are audit logs kept?")["status"] == "ANSWERED"


def test_rejects_empty_and_overlong_questions():
    bot, _ = assistant([RETENTION], answer())

    with pytest.raises(ValueError):
        bot.ask("   ")
    with pytest.raises(ValueError):
        bot.ask("x" * 1001)


def test_chat_endpoint(monkeypatch):
    bot, _ = assistant([RETENTION, UPDATE], answer())
    monkeypatch.setattr(main, "get_assistant", lambda: bot)
    client = TestClient(main.app)

    assert client.post("/chat", json={"question": "Incident reporting deadline?"}).json()["status"] == "ANSWERED"
    response = client.post("/chat", json={"question": " "})
    assert response.status_code == 400 and response.json()["detail"] == "Ask a question."
