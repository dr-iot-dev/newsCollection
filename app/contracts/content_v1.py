import hashlib
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, model_validator

from app.contracts.base import ContractModel


class NormalizedContentV1(ContractModel):
    item_id: UUID
    item_version: int = Field(ge=1)
    snapshot_id: UUID
    canonical_url: AnyHttpUrl
    title: str = Field(min_length=1, max_length=1000)
    body: str
    body_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    published_at: datetime | None = None
    published_date: date | None = None
    modified_at: datetime | None = None
    date_precision: Literal["unknown", "date", "second"]
    language: str = Field(min_length=2, max_length=10)
    language_confidence: float = Field(ge=0, le=1)
    language_source: str
    extraction_method: str
    quality_score: float = Field(ge=0, le=1)
    quality_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def verify_body_hash(self) -> "NormalizedContentV1":
        if self.body_sha256 != hashlib.sha256(self.body.encode()).hexdigest():
            raise ValueError("body_sha256 does not match normalized body")
        return self
