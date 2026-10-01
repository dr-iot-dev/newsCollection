"""Compare supplied, verified facts; never fetch or invent absent comparison values."""

from datetime import date
from uuid import UUID

from app.contracts.comparison_v1 import ComparisonDatasetV1, ComparisonValueV1
from app.contracts.facts_v1 import VerifiedFactV1
from app.core.editorial import EditorialError

SCOPE = "登録済みの承認済み一次情報と指定された参照記事の範囲"
UNAVAILABLE = SCOPE + "では比較対象・条件を確認できていないため比較不能。追加調査が必要。"


def organization(facts: tuple[VerifiedFactV1, ...]) -> set[str]:
    return {f.value.casefold() for f in facts if f.fact_type == "organization"}


def values(facts: tuple[VerifiedFactV1, ...], as_of: date) -> tuple[ComparisonValueV1, ...]:
    return tuple(
        ComparisonValueV1(
            subject=f.subject,
            axis=f.fact_type,
            value=f.value,
            unit=f.unit,
            as_of=as_of,
            region=f.region or "検証済みfactsに記録なし",
            conditions=f.conditions or (
                "測定・価格条件は検証済みfactsに記録なし。"
                "時点は取得確認日。"
            ),
            evidence_id=f.evidence_id,
        )
        for f in facts
    )


def build_comparison(
    item_id: UUID,
    revision: int,
    announced: tuple[VerifiedFactV1, ...],
    previous: tuple[VerifiedFactV1, ...],
    competitor: tuple[VerifiedFactV1, ...],
    as_of: date,
) -> ComparisonDatasetV1:
    company = organization(announced)
    if previous and (not company or organization(previous) != company):
        raise EditorialError("PREVIOUS_PRODUCT_COMPANY_MISMATCH")
    if competitor and (not organization(competitor) or company & organization(competitor)):
        raise EditorialError("COMPETITOR_COMPANY_MISMATCH")
    absent = (
        ComparisonValueV1(
            subject="比較対象未確認",
            axis="comparison",
            value=None,
            as_of=as_of,
            region="未確認",
            conditions=SCOPE,
            evidence_id=None,
            unavailable_reason=UNAVAILABLE,
        ),
    )
    return ComparisonDatasetV1(
        item_id=item_id,
        revision=revision,
        announced_product=values(announced, as_of),
        previous_products=values(previous, as_of) if previous else absent,
        competitor_products=values(competitor, as_of) if competitor else absent,
    )
