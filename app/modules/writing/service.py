from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.editorial_v1 import WritingOutputV1
from app.core.editorial import NAME, EditorialError, numbers, personal_data

POLICY_VERSION = "writing-v1"


def validate_writing(output: WritingOutputV1, package: ArticlePackageV1) -> None:
    allowed = {f.fact_id for f in package.facts}
    if not allowed or allowed != set(package.verified_fact_ids):
        raise EditorialError("ARTICLE_PACKAGE_FACTS_MISSING")
    for paragraph in output.paragraphs:
        if not set(paragraph.fact_ids) <= allowed:
            raise EditorialError("DRAFT_FACT_REFERENCE_INVALID")
    text = "\n".join(
        [
            output.title,
            output.lead,
            *(p.text for p in output.paragraphs),
            output.previous_comparison,
            output.competitor_comparison,
        ]
    )
    evidence = "\n".join(
        f.subject + " " + f.value + " " + (f.unit or "") + " " + (f.attribution or "")
        for f in package.facts
    )
    if package.comparison:
        for v in (*package.comparison.previous_products, *package.comparison.competitor_products):
            evidence += "\n" + v.subject + " " + str(v.value or "") + " " + (v.unit or "")
    if not numbers(text) <= numbers(evidence):
        raise EditorialError("DRAFT_NUMBER_UNSUPPORTED")
    if any(name[0] not in evidence for name in NAME.finditer(text)):
        raise EditorialError("DRAFT_ENTITY_UNSUPPORTED")
    if personal_data(text) or "<" in text or "https://" in text or "http://" in text:
        raise EditorialError("DRAFT_UNSAFE_CONTENT")
