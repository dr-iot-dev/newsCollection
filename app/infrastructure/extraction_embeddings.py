"""Small, bounded batches of the same embedding inputs used by the single-input adapter."""

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from app.core.editorial import EditorialError


@dataclass(frozen=True)
class EmbeddingBatchResponse:
    values: tuple[tuple[float, ...], ...]
    model: str
    tokens: int | None
    request_id: str | None
    latency_ms: int


class OpenAIEmbeddingBatchProvider:
    def __init__(
        self, api_key: str, model: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.api_key, self.model, self.transport = api_key, model, transport

    def embed_many(self, texts: Sequence[str]) -> EmbeddingBatchResponse:
        # At most 96,000 UTF-8 bytes, below the 300,000 aggregate-token API limit.
        if not 1 <= len(texts) <= 16 or any(
            not text.strip() or len(text.encode()) > 6000 for text in texts
        ):
            raise ValueError("invalid embedding batch inputs")
        started = time.monotonic()
        try:
            with httpx.Client(
                transport=self.transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(90, connect=5),
            ) as client:
                with client.stream(
                    "POST",
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": "Bearer " + self.api_key},
                    json={"model": self.model, "input": list(texts), "encoding_format": "float"},
                ) as response:
                    if response.status_code != 200:
                        raise EditorialError("DISTANCE_EMBEDDING_PROVIDER_ERROR", 503)
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 4_000_000:
                            raise EditorialError("DISTANCE_EMBEDDING_RESPONSE_TOO_LARGE")
                    data = json.loads(raw)
                    rows = data["data"]
                    if len(rows) != len(texts) or any(
                        type(row["index"]) is not int for row in rows
                    ):
                        raise ValueError("embedding coverage mismatch")
                    rows = sorted(rows, key=lambda row: row["index"])
                    if [row["index"] for row in rows] != list(range(len(texts))):
                        raise ValueError("embedding indices mismatch")
                    if data["model"] != self.model:
                        raise ValueError("embedding model mismatch")
                    return EmbeddingBatchResponse(
                        tuple(tuple(float(v) for v in row["embedding"]) for row in rows),
                        data["model"],
                        data.get("usage", {}).get("total_tokens"),
                        response.headers.get("x-request-id"),
                        int((time.monotonic() - started) * 1000),
                    )
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
            raise EditorialError("DISTANCE_EMBEDDING_PROVIDER_INVALID", 503) from None
