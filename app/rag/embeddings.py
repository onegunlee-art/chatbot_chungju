"""임베딩 제공자. 기본은 서버 내장 BGE-M3(한국어 강함, 외부 키 불필요)."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol

from app.config import get_settings

log = logging.getLogger(__name__)


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """sentence-transformers 로 BAAI/bge-m3 를 직접 구동."""

    def __init__(self, model_name: str, dim: int) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(
            texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False
        )
        return [v.tolist() for v in vecs]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class VoyageEmbedder:
    """Voyage AI API. VOYAGE_API_KEY 필요."""

    def __init__(self, model_name: str, dim: int, api_key: str) -> None:
        import voyageai

        self._client = voyageai.Client(api_key=api_key)
        self._model = model_name
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = texts[i : i + 64]
            res = self._client.embed(batch, model=self._model, input_type="document")
            out.extend(res.embeddings)
        return out

    def embed_query(self, text: str) -> list[float]:
        res = self._client.embed([text], model=self._model, input_type="query")
        return res.embeddings[0]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "voyage":
        if not s.voyage_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=voyage 인데 VOYAGE_API_KEY 가 없습니다.")
        log.info("embedder: voyage/%s", s.embedding_model)
        return VoyageEmbedder(s.embedding_model, s.embedding_dim, s.voyage_api_key)
    log.info("embedder: local/%s", s.embedding_model)
    return LocalEmbedder(s.embedding_model, s.embedding_dim)
