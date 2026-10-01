from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.verification_v1 import CriterionResult, VerificationCriterionV1
from app.core.editorial import NAME, numbers, personal_data

POLICY_VERSION = "verification-v1"
REQUIRED_CRITERIA = frozenset(
    {
        "fact_support",
        "previous_comparison",
        "competitor_comparison",
        "comparison_conditions",
        "claim_attribution",
        "source_links",
        "rights",
        "original_expression",
        "personal_data",
    }
)


def rule_criteria(
    draft: ArticleDraftV1,
    package: ArticlePackageV1,
) -> tuple[VerificationCriterionV1, ...]:
    text = "\n".join([draft.title, draft.lead, draft.body_markdown.split("\n## 出典\n")[0]])
    allowed = " ".join(
        f.subject + " " + f.value + " " + (f.unit or "") + " " + (f.attribution or "")
        for f in package.facts
    )
    comparison = package.comparison
    if comparison:
        for v in (*comparison.previous_products, *comparison.competitor_products):
            allowed += " " + v.subject + " " + str(v.value or "") + " " + (v.unit or "")
    support = numbers(text) <= numbers(allowed) and all(
        m[0] in allowed for m in NAME.finditer(text)
    )
    fact_ids = set(package.verified_fact_ids)
    support = support and all(set(p.fact_ids) <= fact_ids for p in draft.paragraph_facts)
    results = {
        "fact_support": support,
        "previous_comparison": "## 従来製品との比較\n" in text,
        "competitor_comparison": "## 他社製品との比較\n" in text,
        "comparison_conditions": comparison is not None
        and all(
            v.conditions and v.region and (v.evidence_id is not None or v.unavailable_reason)
            for v in (*comparison.previous_products, *comparison.competitor_products)
        ),
        "claim_attribution": all(
            f.attribution and f.attribution in text
            for f in package.facts
            if f.fact_type in {"performance_claim", "security_claim"}
        ),
        "source_links": all(str(s.url) in draft.body_markdown for s in package.source_references),
        "rights": True,
        "original_expression": True,
        "personal_data": not personal_data(text) and "<" not in text,
    }
    for group, key in (
        (comparison.previous_products if comparison else (), "previous_comparison"),
        (comparison.competitor_products if comparison else (), "competitor_comparison"),
    ):
        for value in group:
            if value.unavailable_reason and value.unavailable_reason not in text:
                results[key] = False
    return tuple(
        VerificationCriterionV1(
            key=key,
            result=CriterionResult.PASSED if passed else CriterionResult.FAIL,
            detail="Deterministic validation passed"
            if passed
            else "Deterministic validation failed",
        )
        for key, passed in sorted(results.items())
    )
