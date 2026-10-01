import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SECRET_KEY = re.compile(r"(authorization|cookie|password|secret|token|api[_-]?key)", re.I)
HTTPS_FIELDS = {"url", "list_url", "terms_url", "privacy_url"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DefaultsConfig(StrictModel):
    interval_minutes: int = Field(default=60, ge=5, le=10080)
    timeout_seconds: int = Field(default=20, ge=1, le=30)
    max_response_bytes: int = Field(default=5_242_880, ge=1024, le=10_485_760)
    user_agent: str = Field(min_length=10, max_length=500)
    language_hint: str | None = Field(default=None, max_length=10)
    publish_mode: Literal["draft_only"] = "draft_only"


class LegalConfig(StrictModel):
    status: Literal["pending", "approved", "blocked", "expired"]
    collection_basis: Literal["official_feed", "public_api", "permitted_web"]
    terms_url: str
    privacy_url: str | None = None
    terms_reviewed_at: datetime | None = None
    robots_reviewed_at: datetime | None = None
    approved_by: str | None = None
    text_use: Literal["facts_only"]
    media_use: Literal["none", "verified_only"]
    notes: str | None = None

    @model_validator(mode="after")
    def approved_has_evidence(self) -> "LegalConfig":
        if self.status == "approved" and (self.terms_reviewed_at is None or not self.approved_by):
            raise ValueError("approved legal config requires terms_reviewed_at and approved_by")
        return self

    def effective_status(self, now: datetime | None = None) -> str:
        current = now or datetime.now(UTC)
        if self.status == "approved" and self.terms_reviewed_at is not None:
            checked = self.terms_reviewed_at
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=UTC)
            if current - checked > timedelta(days=180):
                return "expired"
        return self.status


class SourceBase(StrictModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,99}$")
    name: str = Field(min_length=1, max_length=500)
    enabled: bool = False
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)
    max_response_bytes: int | None = Field(default=None, ge=1024, le=10_485_760)
    user_agent: str | None = Field(default=None, min_length=10, max_length=500)
    language_hint: str | None = Field(default=None, max_length=10)
    min_delay_seconds: float = Field(default=3, ge=1, le=60)
    timezone_hint: str | None = None
    legal: LegalConfig

    @field_validator("timezone_hint")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("unknown publication timezone") from exc
        return value

    def assert_collectable(self, now: datetime | None = None) -> None:
        legal_status = self.legal.effective_status(now)
        if not self.enabled:
            raise PermissionError(f"source {self.key!r} is disabled")
        if legal_status != "approved":
            raise PermissionError(f"source {self.key!r} legal status is {legal_status!r}")


class RssSource(SourceBase):
    type: Literal["rss"]
    allowed_hosts: list[str] = Field(default_factory=list)
    url: str


class GitHubSource(SourceBase):
    type: Literal["github_releases"]
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    include_prereleases: bool = False
    include_drafts: bool = False
    max_pages_per_run: int = Field(default=10, ge=1, le=100)


class WebSelectors(StrictModel):
    list_links: str
    title: str
    published_at: str
    body: str
    next_page: str | None = None


class WebSource(SourceBase):
    type: Literal["web"]
    list_url: str
    allowed_hosts: list[str] = Field(min_length=1)
    allow_url_patterns: list[str] = Field(min_length=1)
    deny_url_patterns: list[str] = Field(default_factory=list)
    selectors: WebSelectors
    min_delay_seconds: float = Field(default=3, ge=1, le=60)
    max_pages_per_run: int = Field(default=20, ge=2, le=100)

    @model_validator(mode="after")
    def valid_web_policy(self) -> "WebSource":
        from soupsieve import compile as compile_selector

        for pattern in self.allow_url_patterns + self.deny_url_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError("invalid URL pattern") from exc
        for selector in self.selectors.model_dump().values():
            if selector:
                try:
                    compile_selector(selector)
                except Exception as exc:
                    raise ValueError("invalid CSS selector") from exc
        if self.legal.status == "approved":
            if self.legal.collection_basis != "permitted_web":
                raise ValueError("Web collection requires permitted_web approval")
            if self.legal.robots_reviewed_at is None:
                raise ValueError("Web approval requires robots_reviewed_at")
        return self


SourceConfig = Annotated[RssSource | GitHubSource | WebSource, Field(discriminator="type")]


class SourcesFile(StrictModel):
    version: Literal[1]
    defaults: DefaultsConfig
    sources: list[SourceConfig]

    @model_validator(mode="after")
    def unique_keys(self) -> "SourcesFile":
        keys = [source.key for source in self.sources]
        if len(keys) != len(set(keys)):
            raise ValueError("source keys must be unique")
        return self


def _scan_raw(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if SECRET_KEY.search(key_text):
                raise ValueError(f"{child_path}: secret-like keys are not allowed")
            if key_text in HTTPS_FIELDS and isinstance(child, str):
                parsed = urlsplit(child)
                if parsed.scheme != "https" or not parsed.hostname:
                    raise ValueError(f"{child_path}: HTTPS URL required")
            _scan_raw(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_raw(child, f"{path}[{index}]")


def load_sources(path: Path) -> SourcesFile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be a mapping")
    _scan_raw(raw)
    return SourcesFile.model_validate(raw)
