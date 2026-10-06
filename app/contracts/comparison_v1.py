from datetime import date
from uuid import UUID

from app.contracts.base import ContractModel
from app.contracts.comparison_analysis_v1 import ComparisonAnalysisV1


class ComparisonValueV1(ContractModel):
    subject: str
    axis: str
    value: str | int | float | bool | None
    unit: str | None = None
    as_of: date
    region: str
    conditions: str
    evidence_id: UUID | None
    unavailable_reason: str | None = None


class ComparisonDatasetV1(ContractModel):
    item_id: UUID
    revision: int
    announced_product: tuple[ComparisonValueV1, ...]
    previous_products: tuple[ComparisonValueV1, ...]
    competitor_products: tuple[ComparisonValueV1, ...]
    analysis: ComparisonAnalysisV1 | None = None
