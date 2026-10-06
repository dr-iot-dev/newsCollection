from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.editorial_v1 import WritingOutputV1
from app.core.draft_style import title_has_comparison_suffix
from app.core.editorial import EditorialError, entities_supported, numbers, personal_data
from app.core.evidence_support import (
    COMPARISON_HEADINGS,
    comparison_available,
    comparison_section_supported,
    price_conditions_supported,
    supported_text,
    vendor_claims_attributed,
)

POLICY_VERSION = "writing-v4"


def validate_writing(output: WritingOutputV1, package: ArticlePackageV1) -> None:
    if len(output.title) > 60:
        raise EditorialError("DRAFT_TITLE_TOO_LONG", path=("title",))
    if title_has_comparison_suffix(output.title):
        raise EditorialError("DRAFT_TITLE_REDUNDANT_SUFFIX", path=("title",))
    allowed = {f.fact_id for f in package.facts}
    if not allowed or allowed != set(package.verified_fact_ids):
        raise EditorialError("ARTICLE_PACKAGE_FACTS_MISSING")
    for index, paragraph in enumerate(output.paragraphs):
        if not set(paragraph.fact_ids) <= allowed:
            raise EditorialError(
                "DRAFT_FACT_REFERENCE_INVALID", path=("paragraphs", index, "fact_ids")
            )
    text = "\n\n".join(
        [
            output.title,
            output.lead,
            *(p.text for p in output.paragraphs),
            output.previous_comparison,
            output.competitor_comparison,
        ]
    )
    evidence = supported_text(package)
    if any(heading in text for heading in COMPARISON_HEADINGS):
        raise EditorialError("DRAFT_COMPARISON_SECTION_FORBIDDEN")
    body = "\n\n".join(
        [
            *(p.text for p in output.paragraphs),
            output.previous_comparison,
            output.competitor_comparison,
        ]
    )
    if package.comparison:
        for field, values in (
            ("previous_comparison", package.comparison.previous_products),
            ("competitor_comparison", package.comparison.competitor_products),
        ):
            comparison_text = body if comparison_available(values) else getattr(output, field)
            if not comparison_section_supported(comparison_text, values):
                raise EditorialError("DRAFT_COMPARISON_CONTENT_MISSING", path=(field,))
    if not vendor_claims_attributed(text):
        raise EditorialError("DRAFT_CLAIM_ATTRIBUTION_MISSING")
    if not price_conditions_supported(text, package):
        raise EditorialError("DRAFT_PRICE_CONDITIONS_MISSING")
    if not numbers(text) <= numbers(evidence):
        raise EditorialError("DRAFT_NUMBER_UNSUPPORTED")
    if not entities_supported(
        text, evidence, tuple(f.value for f in package.facts if f.fact_type == "organization")
    ):
        raise EditorialError("DRAFT_ENTITY_UNSUPPORTED")
    if personal_data(text) or "<" in text or "https://" in text or "http://" in text:
        raise EditorialError("DRAFT_UNSAFE_CONTENT")


def render_comparison(output: WritingOutputV1, package: ArticlePackageV1) -> str:
    if package.comparison is None:
        return ""
    blocks = []
    for values, text in (
        (package.comparison.previous_products, output.previous_comparison),
        (package.comparison.competitor_products, output.competitor_comparison),
    ):
        if comparison_available(values):
            blocks.append(text)
    return "\n\n" + "\n\n".join(blocks) if blocks else ""
