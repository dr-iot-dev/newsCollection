from typing import Literal
from uuid import UUID

from pydantic import Field

from app.contracts.base import ContractModel

FactKind = Literal[
    "organization",
    "product",
    "version",
    "announcement_date",
    "release_date",
    "availability_region",
    "price",
    "currency",
    "hardware_spec",
    "software_requirement",
    "compatibility",
    "performance_claim",
    "security_claim",
    "standard",
    "license",
    "repository",
    "support_end_date",
]


class ExtractedFactV1(ContractModel):
    fact_type: FactKind
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=500)
    unit: str | None = None
    currency: str | None = None
    date_precision: Literal["year", "month", "day"] | None = None
    region: str | None = None
    conditions: str | None = None
    attribution: str | None = None
    evidence_text: str = Field(min_length=1, max_length=1000)
    evidence_start: int = Field(ge=0)
    evidence_end: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)


class FactsOutputV1(ContractModel):
    facts: tuple[ExtractedFactV1, ...] = Field(max_length=100)
    uncertainties: tuple[str, ...] = ()


class VerifiedFactV1(ContractModel):
    fact_id: UUID
    evidence_id: UUID
    fact_type: FactKind
    subject: str
    predicate: str
    value: str
    unit: str | None = None
    currency: str | None = None
    date_precision: Literal["year", "month", "day"] | None = None
    region: str | None = None
    conditions: str | None = None
    attribution: str | None = None
