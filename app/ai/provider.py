"""Tool-free, bounded structured-output provider port and Responses API adapter."""

import copy
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.editorial import EditorialError


@dataclass(frozen=True)
class AIResponse:
    output: dict[str, Any]
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0


class AIProvider(Protocol):
    def generate(
        self,
        *,
        model: str,
        instructions: str,
        data: dict[str, Any],
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> AIResponse: ...


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("format", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


class ResponsesProvider:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._api_key = api_key
        self._transport = transport

    def generate(
        self,
        *,
        model: str,
        instructions: str,
        data: dict[str, Any],
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> AIResponse:
        started = time.monotonic()
        payload = {
            "model": model,
            "instructions": instructions,
            "input": json.dumps(data, ensure_ascii=False),
            "store": False,
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "editorial_result",
                    "strict": True,
                    "schema": strict_schema(schema),
                }
            },
        }
        try:
            with httpx.Client(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(90, connect=5),
            ) as client:
                with client.stream(
                    "POST",
                    "https://api.openai.com/v1/responses",
                    json=payload,
                    headers={"Authorization": "Bearer " + self._api_key},
                ) as response:
                    if response.status_code != 200:
                        raise EditorialError("AI_PROVIDER_ERROR", 503)
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 2_000_000:
                            raise EditorialError("AI_RESPONSE_TOO_LARGE", 503)
                    value = json.loads(chunks)
                    if value.get("status") != "completed":
                        raise EditorialError("AI_RESPONSE_INCOMPLETE", 503)
                    parts = [
                        part
                        for item in value.get("output", [])
                        if item.get("type") == "message"
                        for part in item.get("content", [])
                    ]
                    if any(p.get("type") == "refusal" for p in parts):
                        raise EditorialError("AI_REFUSAL", 503)
                    result = json.loads(
                        "".join(p.get("text", "") for p in parts if p.get("type") == "output_text")
                    )
                    if not isinstance(result, dict):
                        raise ValueError("object required")
                    usage = value.get("usage", {})
                    return AIResponse(
                        result,
                        value.get("id"),
                        usage.get("input_tokens"),
                        usage.get("output_tokens"),
                        int((time.monotonic() - started) * 1000),
                    )
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise EditorialError("AI_PROVIDER_INVALID_RESPONSE", 503) from None
