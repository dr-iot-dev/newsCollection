"""Shared factual support from verified facts and supplied comparison metadata."""

import re

from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.comparison_v1 import ComparisonValueV1
from app.core.editorial import numbers


def supported_text(package: ArticlePackageV1) -> str:
    evidence = "\n".join(
        " ".join(
            str(value or "")
            for value in (
                f.subject,
                f.value,
                f.unit,
                f.currency,
                f.region,
                f.conditions,
                f.attribution,
            )
        )
        for f in package.facts
    )
    if package.comparison:
        for value in (
            *package.comparison.announced_product,
            *package.comparison.previous_products,
            *package.comparison.competitor_products,
        ):
            evidence += "\n" + " ".join(
                str(part or "")
                for part in (
                    value.subject,
                    value.value,
                    value.unit,
                    value.region,
                    value.conditions,
                    value.as_of.isoformat(),
                    value.unavailable_reason,
                )
            )
    return evidence


COMPARISON_HEADINGS = (
    "## 他製品との比較",
    "## 従来製品との比較",
    "## 他社製品との比較",
)


def comparison_available(values: tuple[ComparisonValueV1, ...]) -> bool:
    return (
        bool(values)
        and not any(v.unavailable_reason for v in values)
        and any(v.axis == "product" and v.value and v.evidence_id for v in values)
    )


def comparison_section_supported(text: str, values: tuple[ComparisonValueV1, ...]) -> bool:
    if not comparison_available(values):
        return not text.strip()
    names = [str(v.value) for v in values if v.axis == "product" and v.value]
    return all(name in text for name in names) and "比較不能" not in text


def price_conditions_supported(text: str, package: ArticlePackageV1) -> bool:
    for fact in package.facts:
        if fact.fact_type != "price":
            continue
        subsidized = "補助" in (fact.conditions or "") or "subsidy" in fact.predicate.casefold()
        if not subsidized:
            continue
        price_numbers = numbers(fact.value)
        for block in re.split(r"\n\s*\n|\n##[^\n]+\n", text):
            prices = [
                match[0] for match in re.finditer(r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?\s*円", block)
            ]
            if any(numbers(price) & price_numbers for price in prices) and "補助" not in block:
                return False
    return True


def vendor_claims_attributed(text: str) -> bool:
    claims = ("最先端", "最新", "高い拡張性", "ストレスフリー", "見守りを実現")
    attribution = ("によると", "と説明", "としている", "としています", "と案内", "発表では")
    for block in re.split(r"\n\s*\n|\n##[^\n]+\n", text):
        if any(claim in block for claim in claims) and not any(
            marker in block for marker in attribution
        ):
            return False
    return True
