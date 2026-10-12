"""Bounded embedding generation; all source chunks are retained, never truncated."""

import json
import time
from dataclasses import dataclass

import httpx

from app.core.editorial import EditorialError


@dataclass(frozen=True)
class EmbeddingResponse:
    values: tuple[float, ...]
    model: str
    tokens: int | None
    request_id: str | None
    latency_ms: int


class OpenAIEmbeddings:
    def __init__(
        self, api_key: str, model: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.api_key, self.model, self.transport = api_key, model, transport

    def embed(self, text: str) -> EmbeddingResponse:
        # <= 6,000 UTF-8 bytes also bounds worst-case byte-level tokens below 8,192.
        if not text.strip() or len(text.encode()) > 6000:
            raise EditorialError("PAIR_EMBEDDING_INPUT_LIMIT")
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
                    json={"model": self.model, "input": [text], "encoding_format": "float"},
                ) as response:
                    if response.status_code != 200:
                        raise EditorialError("PAIR_EMBEDDING_PROVIDER_ERROR", 503)
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2_000_000:
                            raise EditorialError("PAIR_EMBEDDING_RESPONSE_TOO_LARGE")
                    data = json.loads(raw)
                    rows = data["data"]
                    if len(rows) != 1 or rows[0]["index"] != 0:
                        raise ValueError("Unexpected embedding coverage")
                    values = tuple(float(n) for n in rows[0]["embedding"])
                    return EmbeddingResponse(
                        values=values,
                        model=data["model"],
                        tokens=data.get("usage", {}).get("total_tokens"),
                        request_id=response.headers.get("x-request-id"),
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
            raise EditorialError("PAIR_EMBEDDING_PROVIDER_INVALID", 503) from None


def embedding_chunks(text: str) -> tuple[str, ...]:
    chunks: list[str] = []
    current = ""
    for character in text:
        if len((current + character).encode()) > 6000:
            chunks.append(current)
            current = ""
        current += character
    if current:
        chunks.append(current)
    if not chunks:
        raise EditorialError("PAIR_EMBEDDING_INPUT_EMPTY")
    return tuple(chunks)
