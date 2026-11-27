"""Internal knowledge: the policy handbook, control register and role directory."""
import csv
import hashlib
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.embeddings import Embedder
from app.models import ControlEvidence, PolicyEvidence

POLICY_DOCUMENT_ID = "policy-handbook"
CONTROL_DOCUMENT_ID = "control-register"
_SECTION = re.compile(r"^##\s+(?P<number>\d+(?:\.\d+)*)[.)]?\s+(?P<heading>.+?)\s*$", re.MULTILINE)
_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class KnowledgeBase(Protocol):
    def search_policies(self, embedding: list[float], limit: int) -> list[PolicyEvidence]: ...
    def search_controls(self, embedding: list[float], limit: int) -> list[ControlEvidence]: ...
    def roles(self) -> list[str]: ...


@dataclass
class Knowledge:
    title: str
    policies: list[PolicyEvidence]
    controls: list[ControlEvidence]
    roles: list[str]
    checksum: str


def _id(kind: str, key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"clauseiq:{kind}:{key}"))


def control_text(control: ControlEvidence) -> str:
    return f"{control.name}. {control.description}"


def load(directory: str | Path) -> Knowledge:
    """Read policy_handbook.md (one `## N. Heading` per section), controls.csv and roles.csv."""
    directory = Path(directory)
    handbook = (directory / "policy_handbook.md").read_text(encoding="utf-8")
    controls_csv = (directory / "controls.csv").read_text(encoding="utf-8")
    roles_csv = (directory / "roles.csv").read_text(encoding="utf-8")

    sections = list(_SECTION.finditer(handbook))
    if not sections:
        raise ValueError("policy_handbook.md has no '## 1. Heading' sections")
    policies = []
    for index, match in enumerate(sections):
        end = sections[index + 1].start() if index + 1 < len(sections) else len(handbook)
        body = handbook[match.end():end].strip()
        if body:
            policies.append(PolicyEvidence(
                chunk_id=_id("policy-section", match.group("number")), document_id=POLICY_DOCUMENT_ID,
                section_number=match.group("number"), heading=match.group("heading"), content=body))

    roles = [row["name"].strip() for row in csv.DictReader(roles_csv.splitlines()) if row["name"].strip()]
    controls = [
        ControlEvidence(
            control_id=row["control_id"].strip(), name=row["name"].strip(), description=row["description"].strip(),
            owner_role=row["owner_role"].strip() or None, frequency=row["frequency"].strip() or None,
            policy_section=row["policy_section"].strip() or None)
        for row in csv.DictReader(controls_csv.splitlines()) if row["control_id"].strip()
    ]
    title = _TITLE.search(handbook)
    checksum = hashlib.sha256("\x00".join((handbook, controls_csv, roles_csv)).encode()).hexdigest()
    return Knowledge(title.group(1) if title else "Policy handbook", policies, controls, roles, checksum)


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


class InMemoryKnowledgeBase:
    """Searches the loaded files directly. Used by the CLI and tests; the worker searches pgvector."""

    def __init__(self, knowledge: Knowledge, embedder: Embedder) -> None:
        self._knowledge = knowledge
        self._policy_vectors = embedder.embed([item.content for item in knowledge.policies])
        self._control_vectors = embedder.embed([control_text(item) for item in knowledge.controls])

    def search_policies(self, embedding: list[float], limit: int) -> list[PolicyEvidence]:
        return self._top(self._knowledge.policies, self._policy_vectors, embedding, limit)

    def search_controls(self, embedding: list[float], limit: int) -> list[ControlEvidence]:
        return self._top(self._knowledge.controls, self._control_vectors, embedding, limit)

    def roles(self) -> list[str]:
        return list(self._knowledge.roles)

    @staticmethod
    def _top(items, vectors, embedding, limit):
        scored = sorted(((_cosine(vector, embedding), item) for item, vector in zip(items, vectors)),
                        key=lambda pair: pair[0], reverse=True)
        return [item.model_copy(update={"similarity": score}) for score, item in scored[:limit]]
