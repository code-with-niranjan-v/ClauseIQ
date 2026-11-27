import re
from pathlib import Path

import pytest

from app import knowledge, workflow
from app.assessment import LlmAssessor, assess_gap, check_role_coverage, resolve_role
from app.embeddings import HashEmbedder
from app.extraction import RuleBasedExtractor
from app.models import Assessment, ControlEvidence, PolicyEvidence
from tests.fakes import MemoryGraph, MemoryRepository, MemoryStore, ScriptedChatModel, make_event

DATA = Path(__file__).resolve().parent.parent / "sample-data"
ROLES = ["Compliance Officer", "SOC Manager", "IAM Manager"]


def test_sample_knowledge_loads():
    loaded = knowledge.load(DATA)

    assert [item.section_number for item in loaded.policies] == [str(number) for number in range(1, 9)]
    assert loaded.policies[4].heading == "Audit logging"
    assert "least once every quarter" in loaded.policies[4].content
    assert len(loaded.controls) == 7 and len(loaded.roles) == 9
    assert {item.control_id for item in loaded.controls if item.owner_role is None} == {"CTRL-006"}
    assert all(item.owner_role in loaded.roles for item in loaded.controls if item.owner_role)


def assessment(model_coverage, policy=True, control_owner="SOC Manager", control=True):
    return Assessment(
        obligation_id="o", model_coverage=model_coverage, explanation="Compared.",
        policies=[PolicyEvidence(chunk_id="p", document_id="d", content="text", matched=policy)],
        controls=[ControlEvidence(control_id="CTRL-1", name="n", description="d", owner_role=control_owner,
                                  matched=control)])


@pytest.mark.parametrize("item, status, finding, severity", [
    (assessment("COVERED"), "COVERED", None, None),
    (assessment("COVERED", control=False), "PARTIALLY_COVERED", "CONTROL_DESIGN_GAP", "MEDIUM"),
    (assessment("COVERED", control_owner=None), "PARTIALLY_COVERED", "OWNERSHIP_GAP", "MEDIUM"),
    (assessment("COVERED", control_owner="Chief Wizard"), "PARTIALLY_COVERED", "OWNERSHIP_GAP", "MEDIUM"),
    (assessment("PARTIALLY_COVERED"), "PARTIALLY_COVERED", "PARTIAL_POLICY_GAP", "MEDIUM"),
    (assessment("CONFLICTING"), "CONFLICTING", "POLICY_CONFLICT", "HIGH"),
    (assessment("NOT_COVERED", policy=False), "NOT_COVERED", "POLICY_GAP", "HIGH"),
    (assessment("UNVERIFIED"), "UNVERIFIED", "IMPLEMENTATION_UNVERIFIED", "LOW"),
    # The model said "covered" but pointed at no policy section that was actually retrieved.
    (assessment("COVERED", policy=False), "UNVERIFIED", "IMPLEMENTATION_UNVERIFIED", "LOW"),
])
def test_gap_rules(item, status, finding, severity):
    decided = assess_gap(check_role_coverage(item, ROLES))

    assert (decided.coverage_status, decided.finding_type, decided.severity) == (status, finding, severity)


def test_covered_never_claims_implementation():
    decided = assess_gap(check_role_coverage(assessment("COVERED"), ROLES))

    assert "Implementation evidence was not assessed" in decided.explanation


def test_assigned_role_always_comes_from_the_directory():
    owned = check_role_coverage(assessment("PARTIALLY_COVERED"), ROLES)
    unowned = check_role_coverage(assessment("PARTIALLY_COVERED", control_owner=None), ROLES)

    assert resolve_role("soc manager", owned, ROLES) == "SOC Manager"
    assert resolve_role("Chief Risk Wizard", owned, ROLES) == "SOC Manager"  # owner of the matched control
    assert resolve_role("Priya from Legal", unowned, ROLES) == "Compliance Officer"


# One reply per obligation in sample-circular.pdf: (keyword, coverage, policy section, control, policy quote)
SCRIPT = [
    ("once every quarter", "COVERED", "5", "CTRL-003", "reviews audit logs at least once every quarter"),
    ("five years", "CONFLICTING", "3", "CTRL-002", "Audit logs and security logs are retained for three years."),
    ("within 6 hours", "PARTIALLY_COVERED", "6", "CTRL-004", "reported to the regulator within one hour"),
    ("third party", "COVERED", "7", "CTRL-006", None),
    ("located in India", "NOT_COVERED", None, None, None),
]


def assess_reply(prompt: str) -> dict:
    obligation = prompt.split("</obligation>")[0]
    _, coverage, section, control, quote = next(row for row in SCRIPT if row[0] in obligation)
    found = re.search(rf'<policy_section id="(P\d+)" number="{section}"', prompt) if section else None
    return {
        "coverageStatus": coverage,
        # P99 and CTRL-999 were never supplied, so they must be dropped.
        "matchedPolicySectionIds": ([found.group(1)] if found else []) + ["P99"],
        "matchedControlIds": ([control] if control and f'<control id="{control}"' in prompt else []) + ["CTRL-999"],
        "policyQuote": quote, "explanation": f"Assessed as {coverage}.", "confidence": 0.8,
    }


def draft_reply(prompt: str) -> dict:
    return {"gapTitle": "Gap: " + prompt.splitlines()[0], "gapDescription": "Description.",
            "draftPolicyText": "The bank must do this.", "recommendedAction": "Update the policy.",
            "assignedRole": "Chief Risk Wizard" if "POLICY_GAP" in prompt.splitlines()[0] else "SOC Manager",
            "suggestedDeadline": "30 days", "requiredEvidence": ["Approved policy version"], "confidence": 0.7}


def build_pipeline(repository=None, graph=None, knowledge_base=None, dimensions=256):
    pdf = (DATA / "circulars" / "sample-circular.pdf").read_bytes()
    event = make_event(pdf)
    embedder = HashEmbedder(dimensions)
    model = ScriptedChatModel({"_LlmAssessment": assess_reply, "_LlmDraft": draft_reply})
    pipeline = workflow.build_workflow(workflow.Dependencies(
        store=MemoryStore({(event.minio_bucket, event.minio_object_key): pdf}), extractor=RuleBasedExtractor(),
        embedder=embedder, repository=repository, graph=graph,
        knowledge=knowledge_base or knowledge.InMemoryKnowledgeBase(knowledge.load(DATA), embedder),
        assessor=LlmAssessor(model), policy_top_k=4, control_top_k=3))
    return event, pipeline, model


def test_sample_circular_produces_covered_and_gap_findings():
    repository, graph = MemoryRepository(), MemoryGraph()
    event, pipeline, model = build_pipeline(repository, graph)

    result = workflow.run(pipeline, event)

    obligations = {item.obligation_id: item for item in result.obligations}
    by_clause = {obligations[item.obligation_id].citation.clause_number: item for item in result.assessments}
    assert set(by_clause) == {"2.1", "2.2", "3.1", "4.1", "5.1"}  # 6.1 "may issue" is not an obligation
    outcome = {clause: (item.coverage_status, item.finding_type, item.severity) for clause, item in by_clause.items()}
    assert outcome == {
        "2.1": ("COVERED", None, None),
        "2.2": ("CONFLICTING", "POLICY_CONFLICT", "HIGH"),
        "3.1": ("PARTIALLY_COVERED", "PARTIAL_POLICY_GAP", "MEDIUM"),
        "4.1": ("PARTIALLY_COVERED", "OWNERSHIP_GAP", "MEDIUM"),  # CTRL-006 has no owner
        "5.1": ("NOT_COVERED", "POLICY_GAP", "HIGH"),
    }
    covered = by_clause["2.1"]
    assert covered.recommendation is None and covered.owner_roles == ["SOC Manager"]
    assert covered.policy_section == "5"
    assert covered.policy_quote == "reviews audit logs at least once every quarter"
    assert by_clause["3.1"].policy_quote is None  # the quote is not in the policy, so it is dropped
    assert by_clause["3.1"].policy_section == "6"
    for item in result.assessments:
        assert [policy for policy in item.policies if policy.matched] or item.finding_type == "POLICY_GAP"
        assert all(control.control_id != "CTRL-999" for control in item.controls)
        assert len(item.policies) == 4 and len(item.controls) == 3
    roles = knowledge.load(DATA).roles
    drafts = [item.recommendation for item in result.assessments if item.finding_type]
    assert len(drafts) == 4 and all(draft.assigned_role in roles for draft in drafts)
    gap = by_clause["5.1"].recommendation
    assert gap.assigned_role == "Compliance Officer"
    assert gap.original_ai_output["assignedRole"] == "Chief Risk Wizard"  # original output is kept
    assert [name for name, _ in model.calls].count("_LlmDraft") == 4
    assert repository.results[event.document_version_id] is result and graph.saved == [result]
