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
