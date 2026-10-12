"""Small execution contract. Never supplies a database or another module."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .protocol import ProtocolError


@dataclass
class StageInput:
    meta: dict[str, Any]
    payload: dict[str, Any]
    assets: dict[str, bytes] = field(default_factory=dict)


@dataclass
class Outcome:
    outcome: str = "success"
    outputs: dict[str, tuple[str, dict[str, Any], dict[str, bytes]]] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def needs(cls, code: str, **details: Any) -> Outcome:
        return cls("needs_input", issues=[{"code": code, "retryable": False, **details}])


@dataclass
class Context:
    config: dict[str, Any] = field(default_factory=dict)
    provider: Any = None
    image_provider: Any = None
    fetch: Any = None
    records: list[dict[str, Any]] = field(default_factory=list)

    def allow_fetch(self, parameters: dict[str, Any]) -> bool:
        setting = self.config.get("fetch_missing_sources", False)
        requested = parameters.get("fetch_missing_sources", setting)
        if type(setting) is not bool or type(requested) is not bool:
            raise ProtocolError("FETCH_SETTING_MUST_BE_BOOLEAN")
        return setting and requested

    def generate(
        self, role: str, data: dict[str, Any], model_type: Any, schema: dict[str, Any] | None = None
    ) -> Any:
        from app.ai.provider import ResponsesProvider

        from .prompts import PROMPTS

        model = self.config.get("models", {}).get(role, "")
        if not isinstance(model, str) or not model.strip() or len(model) > 100:
            raise ProtocolError("AI_MODEL_REQUIRED")
        provider = self.provider
        if provider is None:
            key = os.getenv("AI_API_KEY", "")
            if not key:
                raise ProtocolError("AI_CREDENTIAL_REQUIRED")
            provider = ResponsesProvider(key)
        if len(str(data)) > int(self.config.get("max_input_chars", 200000)):
            raise ProtocolError("AI_INPUT_TOO_LARGE")
        response = provider.generate(
            model=model,
            instructions=PROMPTS[role],
            data=data,
            schema=schema or model_type.model_json_schema(),
            max_output_tokens=int(self.config.get("max_output_tokens", 4000)),
        )
        result = model_type.model_validate(response.output)
        self.records.append(
            {
                "role": role,
                "model": model,
                "provider": "openai" if isinstance(provider, ResponsesProvider) else "injected",
                "request_id": response.request_id,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
        )
        return result


def required(inputs: dict[str, StageInput], role: str) -> StageInput:
    if role not in inputs:
        raise ProtocolError("INPUT_REQUIRED_" + role.upper())
    return inputs[role]


def output(
    role: str, kind: str, payload: dict[str, Any], assets: dict[str, bytes] | None = None
) -> Outcome:
    return Outcome(outputs={role: (kind, payload, assets or {})})


def package_input(inputs: dict[str, StageInput]) -> tuple[Any, dict[str, Any]]:
    from app.contracts.article_package_v1 import ArticlePackageV1

    source = required(inputs, "package").payload
    package = ArticlePackageV1.model_validate(source["package"])
    if set(package.verified_fact_ids) != {fact.fact_id for fact in package.facts}:
        raise ProtocolError("ARTICLE_PACKAGE_FACTS_MISSING")
    return package, source


def require_sources(package: Any, minimum: int) -> None:
    from .protocol import normalize_url

    if minimum < 1 or minimum > 21:
        raise ProtocolError("MINIMUM_SOURCE_SETTING_INVALID")
    urls = {normalize_url(str(ref.url)) for ref in package.source_references if ref.url}
    if len(urls) < minimum:
        raise ProtocolError("COMPARISON_MIN_SOURCES_REQUIRED")
