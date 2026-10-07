from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.verification_v1 import CriterionResult, VerificationCriterionV1
from app.core.article_tables import comparison_prose, render_comparison_table, render_source_list
from app.core.draft_style import has_polite_ending, title_has_comparison_suffix
from app.core.editorial import entities_supported, numbers, personal_data
from app.core.evidence_support import (
    COMPARISON_HEADINGS,
    comparison_available,
    comparison_section_supported,
    price_conditions_supported,
    supported_text,
    vendor_claims_attributed,
)

POLICY_VERSION = "verification-v8"
REQUIRED_CRITERIA = frozenset(
    {
        "fact_support",
        "title_clarity",
        "editorial_conciseness",
        "previous_comparison",
        "competitor_comparison",
        "comparison_conditions",
        "comparison_table",
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
    body = draft.body_markdown.split("\n## 出典\n", 1)[0]
    table = render_comparison_table(package)
    table_valid, prose = comparison_prose(body, package)
    text = "\n\n".join([draft.title, draft.lead, prose])
    allowed = supported_text(package)
    comparison = package.comparison
    support = numbers(text) <= numbers(allowed) and entities_supported(
        text, allowed, tuple(f.value for f in package.facts if f.fact_type == "organization")
    )
    fact_ids = set(package.verified_fact_ids)
    support = support and all(set(p.fact_ids) <= fact_ids for p in draft.paragraph_facts)
    results = {
        "fact_support": support and table_valid,
        "comparison_table": table_valid,
        "title_clarity": 0 < len(draft.title) <= 60
        and not title_has_comparison_suffix(draft.title),
        "editorial_conciseness": not has_polite_ending(text + table),
        "previous_comparison": True,
        "competitor_comparison": True,
        "comparison_conditions": comparison is not None
        and comparison.analysis is not None
        and all(c.decision == "eligible" for c in comparison.analysis.candidates)
        and all(
            v.conditions and v.region and (v.evidence_id is not None or v.unavailable_reason)
            for v in (*comparison.previous_products, *comparison.competitor_products)
        ),
        "claim_attribution": vendor_claims_attributed(text)
        and all(
            f.attribution and f.attribution in text
            for f in package.facts
            if f.fact_type in {"performance_claim", "security_claim"}
        ),
        "source_links": draft.body_markdown.count("\n## 出典\n") == 1
        and draft.body_markdown.split("\n## 出典\n", 1)[-1].strip() == render_source_list(package),
        "rights": True,
        "original_expression": True,
        "personal_data": not personal_data(text)
        and "<" not in text
        and (not table or not personal_data(table)),
    }
    results["comparison_conditions"] = results[
        "comparison_conditions"
    ] and price_conditions_supported(text, package)
    previous = comparison.previous_products if comparison else ()
    competitor = comparison.competitor_products if comparison else ()
    layout_valid = (
        not any(heading in text for heading in COMPARISON_HEADINGS)
        and "比較不能" not in text
        and all(
            v.unavailable_reason not in text
            for v in (*previous, *competitor)
            if v.unavailable_reason
        )
    )
    for group, key in (
        (previous, "previous_comparison"),
        (competitor, "competitor_comparison"),
    ):
        content = prose if comparison_available(group) else ""
        results[key] = layout_valid and comparison_section_supported(content, group)
    return tuple(
        VerificationCriterionV1(
            key=key,
            result=CriterionResult.PASSED if passed else CriterionResult.FAIL,
            detail="No verified reference in this relation; omitted from reader-facing draft"
            if passed
            and key in {"previous_comparison", "competitor_comparison"}
            and not comparison_available(previous if key == "previous_comparison" else competitor)
            else "Deterministic validation passed"
            if passed
            else "Deterministic validation failed",
        )
        for key, passed in sorted(results.items())
    )
