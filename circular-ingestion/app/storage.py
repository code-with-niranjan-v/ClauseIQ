from typing import Protocol

from minio import Minio

from app.config import Settings


class ObjectStore(Protocol):
    def get(self, bucket: str, key: str) -> bytes: ...


class MinioStore:
    def __init__(self, settings: Settings) -> None:
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key or None,
            secret_key=settings.minio_secret_key or None,
            secure=settings.minio_secure,
        )
        self._max_bytes = settings.max_pdf_bytes

    def get(self, bucket: str, key: str) -> bytes:
        response = self._client.get_object(bucket, key)
        try:
            data = response.read(self._max_bytes + 1)
        finally:
            response.close()
            response.release_conn()
        if len(data) > self._max_bytes:
            raise ValueError(f"{bucket}/{key} is larger than MAX_PDF_BYTES")
        return data
