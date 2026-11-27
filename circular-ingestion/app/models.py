from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestionEvent(BaseModel):
    """Event published by circular-scanner on `regulatory.document.ingested`."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    event_id: str = Field(alias="eventId", min_length=1)
    event_type: Literal["REGULATORY_DOCUMENT_INGESTED"] = Field(alias="eventType")
    document_id: str = Field(alias="documentId", min_length=1)
    document_version_id: str = Field(alias="documentVersionId", min_length=1)
    regulator: str
    title: str = ""
    source_url: str = Field(default="", alias="sourceUrl")
    minio_bucket: str = Field(alias="minioBucket", min_length=1)
    minio_object_key: str = Field(alias="minioObjectKey", min_length=1)
    checksum: str = Field(min_length=1)
    created_at: datetime | None = Field(default=None, alias="createdAt")


class Page(BaseModel):
    page_number: int  # 1-based
    text: str


class Chunk(BaseModel):
    id: str
    document_id: str
    document_version_id: str
    page_number: int
    clause_number: str | None = None
    heading: str | None = None
    content: str  # exact slice of the page text
    start_offset: int  # character offsets within the page text
    end_offset: int
    embedding: list[float] | None = None


class Citation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_number: int = Field(alias="pageNumber")
    clause_number: str | None = Field(default=None, alias="clauseNumber")
    quoted_text: str = Field(alias="quotedText")
    start_offset: int | None = Field(default=None, alias="startOffset")
    end_offset: int | None = Field(default=None, alias="endOffset")


class Obligation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    obligation_id: str = Field(alias="obligationId")
    chunk_id: str = Field(alias="chunkId")
    summary: str
    required_action: str = Field(alias="requiredAction")
    responsible_entity: str | None = Field(default=None, alias="responsibleEntity")
    deadline: str | None = None
    applicability: str | None = None
    citation: Citation
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_method: str = Field(default="RULES", alias="extractionMethod")


class RejectedObligation(BaseModel):
    summary: str
    quoted_text: str
    page_number: int
    reason: str


class IngestionResult(BaseModel):
    document_id: str
    document_version_id: str
    page_count: int
    chunks: list[Chunk]
    obligations: list[Obligation]
    rejected: list[RejectedObligation]
    assessments: list["Assessment"] = []


class PolicyEvidence(BaseModel):
    chunk_id: str
    document_id: str
    section_number: str | None = None
    heading: str | None = None
    content: str
    similarity: float = 0.0
    matched: bool = False


class ControlEvidence(BaseModel):
    control_id: str
    name: str
    description: str
    owner_role: str | None = None
    frequency: str | None = None
    policy_section: str | None = None
    similarity: float = 0.0
    matched: bool = False


CoverageStatus = Literal["COVERED", "PARTIALLY_COVERED", "NOT_COVERED", "CONFLICTING", "UNVERIFIED"]
FindingType = Literal["POLICY_GAP", "PARTIAL_POLICY_GAP", "CONTROL_DESIGN_GAP", "OWNERSHIP_GAP",
                      "IMPLEMENTATION_UNVERIFIED", "POLICY_CONFLICT"]


class Recommendation(BaseModel):
    gap_title: str
    gap_description: str
    draft_policy_text: str
    recommended_action: str
    assigned_role: str
    suggested_deadline: str | None = None
    required_evidence: list[str] = []
    confidence: float = 0.0
    original_ai_output: dict = {}


class Assessment(BaseModel):
    """How one obligation maps to internal policies and controls, and the gap if there is one."""

    obligation_id: str
    policies: list[PolicyEvidence] = []  # everything retrieved; `matched` marks what the model relied on
    controls: list[ControlEvidence] = []
    model_coverage: CoverageStatus = "UNVERIFIED"  # what the model said, before the gap rules
    coverage_status: CoverageStatus = "UNVERIFIED"
    explanation: str = ""
    policy_section: str | None = None
    policy_quote: str | None = None
    owner_roles: list[str] = []  # valid owner roles of the matched controls
    finding_type: FindingType | None = None
    severity: Literal["HIGH", "MEDIUM", "LOW"] | None = None
    confidence: float = 0.0
    original_ai_output: dict = {}
    recommendation: Recommendation | None = None


IngestionResult.model_rebuild()
