"""Embedding, generation and individual verification adapters."""

import json
import math
import os
from collections.abc import Sequence

import httpx

STRING = {"type": "string"}


def object_schema(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SELECTION_SCHEMA = object_schema(
    {
        "selection_status": {"type": "string", "enum": ["TWO_SETS", "ONE_SET", "NO_SET"]},
        "primary_article_ids": {"type": "array", "items": STRING},
        "reserve_article_ids": {"type": "array", "items": STRING},
        "reason": STRING,
    }
)
GENERATION_SCHEMA = object_schema(
    {
        "status": {"type": "string", "enum": ["APPROPRIATE", "INAPPROPRIATE"]},
        "reason": STRING,
        "article_markdown": STRING,
    }
)
VERIFICATION_SCHEMA = object_schema(
    {
        "status": {"type": "string", "enum": ["eligible", "ineligible", "needs_confirmation"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reason": STRING,
    }
)


def validate_result(value: dict, schema: dict) -> None:
    if not isinstance(value, dict) or set(value) != set(schema["properties"]):
        raise ValueError("MODEL_OUTPUT_FIELDS")
    for key, spec in schema["properties"].items():
        item = value[key]
        if spec["type"] == "string" and not isinstance(item, str):
            raise ValueError("MODEL_OUTPUT_TYPE")
        if spec["type"] == "array" and (
            not isinstance(item, list) or not all(isinstance(i, str) for i in item)
        ):
            raise ValueError("MODEL_OUTPUT_TYPE")
        if spec["type"] == "integer" and (
            type(item) is not int or not spec["minimum"] <= item <= spec["maximum"]
        ):
            raise ValueError("MODEL_OUTPUT_SCORE")
        if "enum" in spec and item not in spec["enum"]:
            raise ValueError("MODEL_OUTPUT_STATUS")


def chunks(text: str, size: int = 6000) -> list[str]:
    result, current, length = [], [], 0
    for char in text:
        count = len(char.encode("utf-8"))
        if length + count > size:
            result.append("".join(current))
            current, length = [], 0
        current.append(char)
        length += count
    if current:
        result.append("".join(current))
    return result


class OpenAI:
    def __init__(self, key: str | None = None, transport=None):
        self.key = key or os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.key:
            raise ValueError("API_KEY_REQUIRED")
        self.client = httpx.Client(
            base_url="https://api.openai.com/v1/",
            timeout=180,
            transport=transport,
            headers={"Authorization": "Bearer " + self.key},
        )

    def close(self):
        self.client.close()

    def post(self, endpoint: str, payload: dict) -> dict:
        # No automatic repeat of a possibly billed request.
        response = self.client.post(endpoint, json=payload)
        if response.is_error:
            try:
                code = response.json().get("error", {}).get("code", "api_error")
            except ValueError:
                code = "api_error"
            raise ValueError(f"API_ERROR:{response.status_code}:{code}")
        return response.json()

    def complete(self, model: str, prompt: str, data: dict, schema: dict) -> dict:
        payload = {
            "model": model,
            "instructions": prompt,
            "input": json.dumps(data, ensure_ascii=False),
            "store": False,
            "max_output_tokens": 16000,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "result",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        if model.startswith("gpt-6.1-sol"):
            payload["reasoning"] = {"effort": "medium"}
        result = self.post("responses", payload)
        if result.get("status") != "completed":
            raise ValueError("MODEL_RESPONSE_INCOMPLETE")
        parts = []
        for output in result.get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "refusal":
                    raise ValueError("MODEL_REFUSAL")
                if content.get("type") == "output_text":
                    parts.append(content["text"])
        value = json.loads("".join(parts))
        validate_result(value, schema)
        return value

    def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        # Each article is computed here; there is no cross-run embedding cache.
        values = []
        for text in texts:
            sections = chunks(text)
            vectors = []
            for start in range(0, len(sections), 16):
                inputs = sections[start : start + 16]
                result = self.post("embeddings", {"model": model, "input": inputs})
                rows = sorted(result["data"], key=lambda row: row["index"])
                if [r["index"] for r in rows] != list(range(len(inputs))):
                    raise ValueError("EMBEDDING_COVERAGE")
                vectors.extend(r["embedding"] for r in rows)
            if not vectors or len({len(v) for v in vectors}) != 1:
                raise ValueError("EMBEDDING_DIMENSIONS")
            weights = [len(section.encode("utf-8")) for section in sections]
            value = [
                sum(v[i] * w for v, w in zip(vectors, weights, strict=True)) / sum(weights)
                for i in range(len(vectors[0]))
            ]
            norm = math.sqrt(sum(x * x for x in value))
            if not norm or not all(math.isfinite(x) for x in value):
                raise ValueError("EMBEDDING_INVALID")
            values.append([x / norm for x in value])
        return values
