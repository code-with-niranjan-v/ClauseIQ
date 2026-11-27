from pydantic import BaseModel, Field


class IngestionEvent(BaseModel):
    event_id: str = Field(alias="eventId")
    event_type: str = Field(alias="eventType")
    document_id: str = Field(alias="documentId")

    model_config = {"populate_by_name": True}
