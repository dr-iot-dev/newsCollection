"""Explicit article binding for completed, independently checked selection audits."""

from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.comparison_selection_v1 import CandidateEvaluationV1, ComparisonSelectionAuditV1
from app.core.comparison_selection import group_issues
from app.core.content import normalize_url
from app.core.editorial import EditorialError


def selection_group(audit: ComparisonSelectionAuditV1) -> tuple[CandidateEvaluationV1, ...]:
    if (
        audit.outcome != "eligible"
        or audit.plan.plan.context_status != "ready"
        or audit.independent is None
        or audit.independent_ai_run_id is None
        or audit.independent.blocking_issues
        or any(c.result != "pass" for c in audit.independent.checks)
    ):
        raise EditorialError("ARTICLE_SELECTION_NOT_APPROVED")
    entries = {e.product.product_key: e for e in audit.evaluations}
    try:
        group = tuple(entries[key] for key in audit.selected_product_keys)
    except KeyError:
        raise EditorialError("ARTICLE_SELECTION_NOT_APPROVED") from None
    if group_issues(audit.plan.plan, group, audit.minimum_products, audit.minimum_sources):
        raise EditorialError("ARTICLE_SELECTION_NOT_APPROVED")
    return group


def validate_selection_package(package: ArticlePackageV1) -> tuple[CandidateEvaluationV1, ...]:
    audit = package.comparison_selection
    if audit is None:
        return ()
    group = selection_group(audit)
    documents = tuple(d for e in group for d in e.product.documents)
    if (
        audit.item_id != package.item_id
        or audit.plan.item_id != package.item_id
        or audit.plan.item_version != package.item_version
        or [(d.item_id, normalize_url(d.url)) for d in documents]
        != [(r.reference_id, normalize_url(str(r.url))) for r in package.source_references]
    ):
        raise EditorialError("ARTICLE_SELECTION_SOURCE_MISMATCH")
    facts = {f.fact_id: f for f in package.facts}
    owners = {r.reference_id: set(r.fact_ids) for r in package.source_references}
    for entry in group:
        anchors = [entry.product.identity, *entry.evaluation.reason.evidence]
        anchors.extend(a for cell in entry.evaluation.cells for a in cell.evidence)
        for anchor in anchors:
            fact = facts.get(anchor.fact_id)
            if (
                fact is None
                or fact.evidence_id != anchor.evidence_id
                or anchor.fact_id not in owners.get(anchor.item_id, set())
            ):
                raise EditorialError("ARTICLE_SELECTION_FACT_MISMATCH")
    return group
