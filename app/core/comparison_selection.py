"""Deterministic evidence, product identity and coverage checks.

These checks do not pretend to determine semantic fit. A separate AI evaluation
and independent review supply that judgment; scores cannot override failures.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from unicodedata import normalize
from uuid import UUID

from app.contracts.comparison_selection_ai_v1 import (
    CandidateSuitabilityAIOutputV1,
    ComparisonPlanAIOutputV1,
)
from app.contracts.comparison_selection_v1 import (
    CandidateEvaluationV1,
    CandidateSuitabilityV1,
    ComparedProductV1,
    ComparisonPlanOutputV1,
    ComparisonSuitabilityOutputV1,
    GroundedJudgmentV1,
    GroundingV1,
    ProductDocumentV1,
    SourceExclusionBaselineV1,
)
from app.contracts.evidence_v1 import EvidencePackageV1
from app.core.article_tables import table_cell
from app.core.content import normalize_url
from app.core.draft_style import plain_style
from app.core.editorial import EditorialError, numbers


@dataclass(frozen=True)
class GroundedSource:
    document: ProductDocumentV1
    body: str
    evidence: EvidencePackageV1
    anchors: Mapping[UUID, GroundingV1]


def bind_plan(output: ComparisonPlanAIOutputV1, source: GroundedSource) -> ComparisonPlanOutputV1:
    data = output.model_dump(mode="json")
    for field in ("product", "product_kind", "role", "audience", "environment", "purpose"):
        judgment = getattr(output, field)
        try:
            anchors = [source.anchors[key].model_dump(mode="json") for key in judgment.fact_ids]
        except KeyError:
            raise EditorialError("COMPARISON_GROUNDING_INVALID") from None
        data[field] = {"text": judgment.text, "evidence": anchors}
    return ComparisonPlanOutputV1.model_validate(data)


def bind_candidate(
    output: CandidateSuitabilityAIOutputV1,
    source: GroundedSource,
) -> CandidateSuitabilityV1:
    data = output.model_dump(mode="json")
    try:
        data["reason"] = {
            "text": output.reason.text,
            "evidence": [
                source.anchors[key].model_dump(mode="json") for key in output.reason.fact_ids
            ],
        }
        for cell, raw in zip(output.cells, data["cells"], strict=True):
            raw.pop("fact_ids")
            raw["evidence"] = [source.anchors[key].model_dump(mode="json") for key in cell.fact_ids]
    except KeyError:
        raise EditorialError("COMPARISON_GROUNDING_INVALID") from None
    return CandidateSuitabilityV1.model_validate(data)


def primary_product(source: GroundedSource) -> ComparedProductV1:
    facts = source.evidence.verified_facts
    products = [f for f in facts if f.fact_type == "product"]
    companies = [f for f in facts if f.fact_type == "organization"]
    if len(products) != 1 or len(companies) != 1:
        raise EditorialError("COMPARISON_PRIMARY_IDENTITY_AMBIGUOUS")
    product, company = products[0], companies[0]
    anchor = source.anchors.get(product.fact_id)
    if anchor is None:
        raise EditorialError("COMPARISON_PRODUCT_GROUNDING_REQUIRED")
    validate_anchor(anchor, {source.document.item_id: source})
    key = normalize("NFKC", company.value + ":" + product.value).casefold().strip()
    return ComparedProductV1(
        product_key=key, name=product.value, identity=anchor, documents=(source.document,)
    )


def validate_anchor(anchor: GroundingV1, sources: Mapping[UUID, GroundedSource]) -> None:
    source = sources.get(anchor.item_id)
    fact = (
        next((f for f in source.evidence.verified_facts if f.fact_id == anchor.fact_id), None)
        if source
        else None
    )
    if (
        source is None
        or fact is None
        or fact.evidence_id != anchor.evidence_id
        or source.anchors.get(anchor.fact_id) != anchor
        or source.body[anchor.start : anchor.end] != anchor.quote
        or fact.value not in anchor.quote
        or anchor.end <= anchor.start
    ):
        raise EditorialError("COMPARISON_GROUNDING_INVALID")


def validate_judgment(
    judgment: GroundedJudgmentV1,
    sources: Mapping[UUID, GroundedSource],
    allowed_items: set[UUID],
) -> None:
    for anchor in judgment.evidence:
        validate_anchor(anchor, sources)
        if anchor.item_id not in allowed_items:
            raise EditorialError("COMPARISON_OTHER_PRODUCT_GROUNDING")
    if not numbers(judgment.text) <= numbers(" ".join(a.quote for a in judgment.evidence)):
        raise EditorialError("COMPARISON_JUDGMENT_UNSUPPORTED_NUMBER")


def validate_plan(plan: ComparisonPlanOutputV1, source: GroundedSource) -> None:
    sources = {source.document.item_id: source}
    for field in ("product", "product_kind", "role", "audience", "environment", "purpose"):
        validate_judgment(getattr(plan, field), sources, set(sources))
    primary = primary_product(source)
    if plan.product.text != primary.name or primary.identity not in plan.product.evidence:
        raise EditorialError("COMPARISON_PLAN_PRODUCT_MISMATCH")


def excluded(source: GroundedSource, baseline: SourceExclusionBaselineV1 | None) -> bool:
    if baseline is None:
        return False
    doc = source.document
    return any(
        normalize_url(e.url) == normalize_url(doc.url)
        or (e.body_hash is not None and e.body_hash == doc.body_hash)
        or (e.announcement_key is not None and e.announcement_key == doc.announcement_key)
        for e in baseline.entries
    )


def validate_candidate(
    output: CandidateSuitabilityV1,
    plan: ComparisonPlanOutputV1,
    product: ComparedProductV1,
    sources: Mapping[UUID, GroundedSource],
) -> None:
    own = {d.item_id for d in product.documents}
    validate_judgment(output.reason, sources, own)
    literal_name = product.name.split("\uff08", 1)[0].strip()
    if literal_name.casefold() not in output.reason.text.casefold():
        raise EditorialError("COMPARISON_REASON_PRODUCT_MISMATCH")
    keys = {q.key for q in plan.questions}
    if len(output.cells) != len(keys) or {c.question_key for c in output.cells} != keys:
        raise EditorialError("COMPARISON_QUESTION_SET_MISMATCH")
    missing = set()
    for cell_index, cell in enumerate(output.cells):
        if cell.status == "unknown":
            if cell.evidence:
                raise EditorialError("COMPARISON_UNKNOWN_WITH_EVIDENCE")
        elif not cell.evidence:
            raise EditorialError("COMPARISON_CELL_GROUNDING_REQUIRED")
        for anchor in cell.evidence:
            validate_anchor(anchor, sources)
            if anchor.item_id not in own:
                raise EditorialError("COMPARISON_OTHER_PRODUCT_GROUNDING")
            fact = next(
                f
                for f in sources[anchor.item_id].evidence.verified_facts
                if f.fact_id == anchor.fact_id
            )
            preserved = " ".join((cell.answer, *cell.conditions))
            for field in ("conditions", "region", "attribution", "unit", "currency"):
                condition = getattr(fact, field)
                if condition and condition not in preserved:
                    raise EditorialError(
                        "COMPARISON_CELL_CONDITION_LOST", path=("cells", cell_index, "conditions")
                    )
            if fact.conditions and cell.status not in {"conditional", "planned", "incomparable"}:
                raise EditorialError(
                    "COMPARISON_CELL_CONDITION_STATUS_INVALID",
                    path=("cells", cell_index, "status"),
                )
        quoted = " ".join(a.quote for a in cell.evidence)
        for qualifier in (cell.plan, cell.version, cell.region, cell.as_of):
            if qualifier and qualifier not in quoted:
                raise EditorialError("COMPARISON_CELL_QUALIFIER_UNGROUNDED")
        if not numbers(" ".join((cell.answer, *cell.conditions))) <= numbers(quoted):
            raise EditorialError(
                "COMPARISON_CELL_UNSUPPORTED_NUMBER", path=("cells", cell_index, "answer")
            )
        if cell.status in {"unknown", "incomparable"}:
            missing.add(cell.question_key)
    required_missing = missing & {q.key for q in plan.questions if q.required}
    if set(output.missing_question_keys) != required_missing:
        raise EditorialError("COMPARISON_MISSING_QUESTIONS_MISMATCH")
    fits = (output.role_fit, output.purpose_fit, output.audience_fit)
    if output.decision == "eligible" and (any(v != "pass" for v in fits) or required_missing):
        raise EditorialError("COMPARISON_REQUIRED_CONDITION_FAILED")
    if output.decision == "needs_information" and "fail" in fits:
        raise EditorialError("COMPARISON_REJECTED_ROLE_REQUIRED")


def group_issues(
    plan: ComparisonPlanOutputV1,
    group: Sequence[CandidateEvaluationV1],
    minimum_products: int,
    minimum_sources: int,
) -> tuple[str, ...]:
    issues = []
    keys = [e.product.product_key for e in group]
    if len(set(keys)) != len(keys):
        issues.append("COMPARISON_DUPLICATE_PRODUCT")
    if len(set(keys)) < minimum_products:
        issues.append("COMPARISON_MIN_PRODUCTS_REQUIRED")
    documents = [d for e in group for d in e.product.documents]
    if len({normalize_url(d.url) for d in documents}) < minimum_sources:
        issues.append("COMPARISON_MIN_SOURCES_REQUIRED")
    if len({d.body_hash for d in documents}) != len(documents):
        issues.append("COMPARISON_DUPLICATE_CONTENT")
    announcements = {d.announcement_key for d in documents if d.role == "announcement"}
    if not announcements:
        issues.append("COMPARISON_ANNOUNCEMENT_REQUIRED")
    for question in plan.questions:
        products = set()
        documented_announcements: set[str] = set()
        for entry in group:
            if entry.evaluation.decision != "eligible":
                issues.append("COMPARISON_INELIGIBLE_PRODUCT")
            cell = next((c for c in entry.evaluation.cells if c.question_key == question.key), None)
            if cell is None or cell.status in {"unknown", "incomparable"} or not cell.evidence:
                continue
            products.add(entry.product.product_key)
            cited_items = {a.item_id for a in cell.evidence}
            documented_announcements.update(
                d.announcement_key
                for d in entry.product.documents
                if d.role == "announcement" and d.item_id in cited_items
            )
        if question.required and len(products) != len(keys):
            issues.append("COMPARISON_REQUIRED_QUESTION_MISSING:" + question.key)
        if len(products) <= len(set(keys)) // 2:
            issues.append("COMPARISON_PRODUCT_MAJORITY_REQUIRED:" + question.key)
        if len(documented_announcements) <= len(announcements) // 2:
            issues.append("COMPARISON_ANNOUNCEMENT_MAJORITY_REQUIRED:" + question.key)
    return tuple(dict.fromkeys(issues))


def choose_group(
    plan: ComparisonPlanOutputV1,
    target: CandidateEvaluationV1,
    candidates: Sequence[CandidateEvaluationV1],
    minimum_products: int,
    minimum_sources: int,
) -> tuple[CandidateEvaluationV1, ...]:
    pool = sorted(
        (e for e in candidates if e.evaluation.decision == "eligible"),
        key=lambda e: (-e.evaluation.score, e.product.product_key),
    )
    for size in range(minimum_products - 1, len(pool) + 1):
        valid = [
            g
            for refs in combinations(pool, size)
            if not group_issues(plan, g := (target, *refs), minimum_products, minimum_sources)
        ]
        if valid:
            return max(valid, key=lambda g: sum(e.evaluation.score for e in g))
    return ()


def validate_independent(
    output: ComparisonSuitabilityOutputV1,
    group: Sequence[CandidateEvaluationV1],
    sources: Mapping[UUID, GroundedSource],
) -> None:
    own = {d.item_id for e in group for d in e.product.documents}
    allowed = {f.fact_id for key in own for f in sources[key].evidence.verified_facts}
    for check in output.checks:
        if not set(check.fact_ids) <= allowed:
            raise EditorialError("COMPARISON_REVIEW_FACT_REFERENCE_INVALID")
        if check.result == "pass" and not check.fact_ids:
            raise EditorialError("COMPARISON_REVIEW_GROUNDING_REQUIRED")


def render_selection_table(
    plan: ComparisonPlanOutputV1,
    group: Sequence[CandidateEvaluationV1],
) -> str:
    """Concrete questions form rows; products form columns; cells cite their own URLs."""
    docs = {d.item_id: d for e in group for d in e.product.documents}
    urls = tuple(dict.fromkeys(d.url for d in docs.values()))
    header = "| 比較項目 | " + " | ".join(table_cell(e.product.name) for e in group) + " |"
    rows = [header, "| " + " | ".join("---" for _ in range(len(group) + 1)) + " |"]
    statuses = {
        "unknown": "未記載",
        "unsupported": "明示的な非対応",
        "planned": "提供予定",
        "conditional": "条件付き",
        "incomparable": "条件が揃わず比較不能",
    }
    for question in plan.questions:
        cells = []
        for entry in group:
            cell = next(c for c in entry.evaluation.cells if c.question_key == question.key)
            text = table_cell(plain_style(cell.answer))
            if cell.status != "documented":
                text = statuses[cell.status] + ": " + text
            if cell.conditions:
                text += "\uff08" + table_cell("、".join(cell.conditions)) + "\uff09"
            cited = dict.fromkeys(docs[a.item_id].url for a in cell.evidence)
            text += " " + " ".join(f"[資料{urls.index(url) + 1}]({url})" for url in cited)
            cells.append(text.rstrip())
        rows.append("| " + " | ".join([table_cell(question.label), *cells]) + " |")
    return "\n".join(rows)
