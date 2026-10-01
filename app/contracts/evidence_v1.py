from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from app.contracts.base import ContractModel


class FactReferenceV1(ContractModel):
    fact_id: UUID
    evidence_id: UUID
    fact_type: str


class EvidencePackageV1(ContractModel):
    item_id: UUID
    item_version: int = Field(default=1, ge=1)
    canonical_url: AnyHttpUrl
    title: str = Field(min_length=1, max_length=1000)
    published_at: datetime | None = None
    language: str = Field(min_length=2, max_length=10)
    facts: tuple[FactReferenceV1, ...]
    quality_score: float = Field(ge=0, le=1)
    rights_blocked: bool = False
