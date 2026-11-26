import hashlib
import logging
import math
import time
from typing import Protocol

import httpx

from app.config import get_settings
from app.rate_limiter import RateLimitBudgetExceeded, RedisTokenBucket, get_embedding_rate_limiter

logger = logging.getLogger(__name__)


class EmbeddingRateLimitError(Exception):
    """Retryable error raised on HTTP 429 or global token-bucket saturation."""


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str], *, task: str = "retrieval.passage") -> list[list[float]]:
        ...


def estimate_tokens(texts: list[str]) -> int:
    """Fast character-to-token approximation (~4 chars/token) for rate limiting."""
    return max(1, sum(len(t) for t in texts) // 4)


class DeterministicFallbackEmbedder:
    """Offline deterministic n-gram projection embedder for local dev/testing without API keys."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed_texts(self, texts: list[str], *, task: str = "retrieval.passage") -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            tokens = text.lower().split()
            if not tokens:
                vec[0] = 1.0
                vectors.append(vec)
                continue
            for tok in tokens:
                digest = hashlib.sha256(tok.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "big") % self.dim
                sign = 1.0 if (digest[4] & 1) == 0 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class JinaEmbeddingClient:
    """Batched Jina Embeddings v3 client guarded by the global Redis Token Bucket."""

    API_URL = "https://api.jina.ai/v1/embeddings"

    def __init__(
        self,
        api_key: str,
        model: str = "jina-embeddings-v3",
        dim: int = 1024,
        rate_limiter: RedisTokenBucket | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.rate_limiter = rate_limiter

    def embed_texts(self, texts: list[str], *, task: str = "retrieval.passage") -> list[list[float]]:
        if not texts:
            return []

        if self.rate_limiter is not None:
            try:
                self.rate_limiter.acquire(tokens=estimate_tokens(texts), requests=1, timeout_seconds=30.0)
            except RateLimitBudgetExceeded as exc:
                raise EmbeddingRateLimitError(str(exc)) from exc

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "task": task,
            "dimensions": self.dim,
            "late_chunking": False,
            "input": texts,
        }

        with httpx.Client(timeout=60.0) as client:
            response = None
            for attempt in range(3):
                response = client.post(self.API_URL, headers=headers, json=payload)
                if response.status_code != 429 or attempt == 2:
                    break
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 4.0 * (attempt + 1)
                except ValueError:
                    delay = 4.0 * (attempt + 1)
                time.sleep(max(2.0, min(12.0, delay)))

        assert response is not None
        if response.status_code == 429:
            raise EmbeddingRateLimitError("Jina Embeddings API returned 429 Too Many Requests.")
        response.raise_for_status()

        data = response.json()
        items = sorted(data["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in items]


def get_embedding_provider(*, use_rate_limiter: bool = True) -> EmbeddingProvider:
    settings = get_settings()
    if settings.jina_api_key:
        limiter = None
        if use_rate_limiter:
            try:
                limiter = get_embedding_rate_limiter()
            except Exception as exc:  # pragma: no cover - defensive fallback if Redis is absent
                logger.warning("Redis rate limiter unavailable for embeddings: %s", exc)
        return JinaEmbeddingClient(
            api_key=settings.jina_api_key,
            model=settings.jina_embedding_model,
            dim=settings.embedding_dim,
            rate_limiter=limiter,
        )

    logger.warning("JINA_API_KEY not set; using DeterministicFallbackEmbedder (dev/test only).")
    return DeterministicFallbackEmbedder(dim=settings.embedding_dim)
