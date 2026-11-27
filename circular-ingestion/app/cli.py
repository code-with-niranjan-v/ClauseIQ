"""Run the whole pipeline on a local PDF without Kafka, MinIO or databases.

    python -m app.cli sample-data/circulars/sample-circular.pdf

Needs OPENAI_API_KEY. Policies, controls and roles are read from KNOWLEDGE_DIR.
Prints the obligations, their coverage and the drafted findings as JSON.
"""
import hashlib
import json
import sys
from pathlib import Path

from app import knowledge, workflow
from app.assessment import LlmAssessor
from app.config import settings
from app.embeddings import build_embedder
from app.extraction import build_extractor
from app.llm import ConfigurationError, build_chat_model
from app.models import IngestionEvent


class _FileStore:
    def get(self, bucket: str, key: str) -> bytes:
        return Path(key).read_bytes()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    event = IngestionEvent(
        eventId="local", eventType="REGULATORY_DOCUMENT_INGESTED", documentId="local-document",
        documentVersionId="local-version", regulator="LOCAL", title=path.name, sourceUrl=str(path),
        minioBucket="local", minioObjectKey=str(path), checksum=hashlib.sha256(path.read_bytes()).hexdigest())
    try:
        model = build_chat_model(settings)
        embedder = build_embedder(settings)
    except ConfigurationError as error:
        print(error, file=sys.stderr)
        return 1
    pipeline = workflow.build_workflow(workflow.Dependencies(
        store=_FileStore(), extractor=build_extractor(settings, model), embedder=embedder,
        repository=None, graph=None, chunk_max_chars=settings.chunk_max_chars,
        knowledge=knowledge.InMemoryKnowledgeBase(knowledge.load(settings.knowledge_dir), embedder),
        assessor=LlmAssessor(model), policy_top_k=settings.policy_top_k, control_top_k=settings.control_top_k))
    result = workflow.run(pipeline, event)
    assessments = {item.obligation_id: item for item in result.assessments}
    obligations = []
    for item in result.obligations:
        row = item.model_dump(by_alias=True, exclude={"chunk_id"})
        assessed = assessments.get(item.obligation_id)
        if assessed:
            row["coverage"] = {
                "coverageStatus": assessed.coverage_status,
                "explanation": assessed.explanation,
                "policySection": assessed.policy_section,
                "policyQuote": assessed.policy_quote,
                "controls": [control.control_id for control in assessed.controls if control.matched],
                "ownerRoles": assessed.owner_roles,
            }
            if assessed.finding_type and assessed.recommendation:
                draft = assessed.recommendation
                row["finding"] = {
                    "findingType": assessed.finding_type, "severity": assessed.severity, "status": "PENDING_REVIEW",
                    "title": draft.gap_title, "description": draft.gap_description,
                    "draftPolicyText": draft.draft_policy_text, "recommendedAction": draft.recommended_action,
                    "assignedRole": draft.assigned_role, "suggestedDeadline": draft.suggested_deadline,
                    "requiredEvidence": draft.required_evidence, "confidence": draft.confidence,
                }
        obligations.append(row)
    print(json.dumps({
        "documentId": result.document_id, "pageCount": result.page_count, "chunkCount": len(result.chunks),
        "obligations": obligations, "rejected": [item.model_dump() for item in result.rejected],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
