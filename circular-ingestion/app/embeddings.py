import hashlib
import math
import re
from typing import Protocol

from app.config import Settings

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic bag-of-words hashing vectors.

    An offline placeholder for tests (EMBEDDING_PROVIDER=hash). It matches
    shared words, not meaning.
    """

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.sha1(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


class OpenAIEmbedder:
    def __init__(self, settings: Settings) -> None:
        from langchain_openai import OpenAIEmbeddings

        from app.llm import require_key

        options: dict = {"model": settings.embedding_model, "dimensions": settings.embedding_dimensions,
                         "api_key": require_key(settings)}
        if settings.llm_base_url:
            options["base_url"] = settings.llm_base_url
        self._client = OpenAIEmbeddings(**options)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hash":
        return HashEmbedder(settings.embedding_dimensions)
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {settings.embedding_provider}")
