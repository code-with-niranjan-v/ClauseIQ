import hashlib

from app.models import IngestionEvent, IngestionResult


class MemoryStore:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects

    def get(self, bucket: str, key: str) -> bytes:
        return self.objects[(bucket, key)]


class MemoryRepository:
    def __init__(self) -> None:
        self.status: dict[str, str] = {}
        self.attempts: dict[str, int] = {}
        self.results: dict[str, IngestionResult] = {}
        self.errors: list[str] = []

    def begin_event(self, event: IngestionEvent) -> bool:
        if self.status.get(event.event_id) == "COMPLETED":
            return False
        self.status[event.event_id] = "PROCESSING"
        self.attempts[event.event_id] = self.attempts.get(event.event_id, 0) + 1
        return True

    def save_result(self, event: IngestionEvent, result: IngestionResult) -> None:
        self.results[event.document_version_id] = result
        self.status[event.event_id] = "COMPLETED"

    def fail_event(self, event: IngestionEvent, error: str, final: bool) -> None:
        self.status[event.event_id] = "DEAD_LETTERED" if final else "FAILED"
        self.errors.append(error)


class MemoryGraph:
    def __init__(self) -> None:
        self.saved: list[IngestionResult] = []

    def save(self, event: IngestionEvent, result: IngestionResult) -> None:
        self.saved.append(result)


def make_event(pdf: bytes, **overrides) -> IngestionEvent:
    """An event shaped exactly like circular-scanner's OutboxPublisher payload."""
    payload = {
        "eventId": "0b0f6f2e-58a1-3c55-9d5c-1f0f8a2f7a11",
        "eventType": "REGULATORY_DOCUMENT_INGESTED",
        "documentId": "5a8e6c1e-3f0b-3d7e-8a43-2b9d1c7e4f10",
        "documentVersionId": "0b0f6f2e-58a1-3c55-9d5c-1f0f8a2f7a11",
        "regulator": "RBI",
        "title": "Circular on Audit Logging",
        "sourceUrl": "https://www.rbi.org.in/sample.pdf",
        "minioBucket": "regulatory-originals",
        "minioObjectKey": "RBI/5a8e6c1e-3f0b-3d7e-8a43-2b9d1c7e4f10/version-1/original.pdf",
        "checksum": hashlib.sha256(pdf).hexdigest(),
        "createdAt": "2026-11-27T06:00:01.123456Z",
    }
    payload.update(overrides)
    return IngestionEvent.model_validate(payload)
