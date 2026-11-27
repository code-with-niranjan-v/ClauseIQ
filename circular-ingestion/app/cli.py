"""Run the pipeline on a local PDF without Kafka, MinIO or databases.

    python -m app.cli path/to/circular.pdf

Prints the extracted obligations as JSON in the shape PLAN.md specifies.
"""
import hashlib
import json
import sys
from pathlib import Path

from app import workflow
from app.config import settings
from app.embeddings import build_embedder
from app.extraction import build_extractor
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
        minioBucket="local", minioObjectKey=str(path),
        checksum=hashlib.sha256(path.read_bytes()).hexdigest())
    pipeline = workflow.build_workflow(workflow.Dependencies(
        store=_FileStore(), extractor=build_extractor(settings), embedder=build_embedder(settings),
        repository=None, graph=None, chunk_max_chars=settings.chunk_max_chars))
    result = workflow.run(pipeline, event)
    print(json.dumps({
        "documentId": result.document_id,
        "pageCount": result.page_count,
        "chunkCount": len(result.chunks),
        "obligations": [item.model_dump(by_alias=True, exclude={"chunk_id"}) for item in result.obligations],
        "rejected": [item.model_dump() for item in result.rejected],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
