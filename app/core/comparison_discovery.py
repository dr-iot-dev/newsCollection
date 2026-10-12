"""Joint-hypothesis guards reuse literal evidence primitives, never V1 approval."""

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.contracts.base import ContractModel
from app.contracts.comparison_discovery_v2 import (
    ComparisonDiscoveryAuditV2,
    ComparisonDiscoveryRequestV2,
    ComparisonGroupEvaluationV2,
    ComparisonHypothesisOutputV2,
    DiscoveryEvidenceInventoryV2,
    DiscoveryGroupSelectionV2,
    DiscoveryReviewV2,
    DiscoverySemanticProfilesV2,
    FactContextBindingV2,
    SourceContextSpanV2,
)
from app.contracts.comparison_selection_ai_v1 import (
    CandidateSuitabilityAIOutputV1,
    GroundedJudgmentRefV1,
)
from app.contracts.comparison_selection_v1 import ComparisonCellV1
from app.contracts.envelope import canonical_payload_hash
from app.core.comparison_selection import (
    GroundedSource,
    bind_candidate,
    primary_product,
    validate_anchor,
)
from app.core.content import normalize_url
from app.core.editorial import EditorialBatchError, EditorialError, numbers

FACT_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def normalize_judgment_references[T: ContractModel](value: T, allowed_fact_ids: set[UUID]) -> T:
    """Move known inline fact UUIDs into references; never erase unknown IDs or numbers."""

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            if isinstance(node.get("text"), str) and isinstance(node.get("fact_ids"), list):
                matches = FACT_UUID.findall(node["text"])
                ids = [UUID(match) for match in matches]
                if not set(ids) <= allowed_fact_ids:
                    raise EditorialError("DISCOVERY_FACT_REFERENCE_INVALID")
                if ids:
                    node["fact_ids"] = list(
                        dict.fromkeys((*node["fact_ids"], *(str(k) for k in ids)))
                    )
                    node["text"] = FACT_UUID.sub("", node["text"])
                    node["text"] = re.sub(r"\(\s*\)|\uff08\s*\uff09", "", node["text"]).strip()
            for child in node.values():
                visit(child)

    data = value.model_dump(mode="json")
    visit(data)
    return type(value).model_validate(data)


def contexts(source: GroundedSource) -> tuple[FactContextBindingV2, ...]:
    result = []
    for anchor in source.anchors.values():
        # Keep paragraph neighbours and table headings/notes within a bounded window.
        start, end = max(0, anchor.start - 650), min(len(source.body), anchor.end + 650)
        result.append(
            FactContextBindingV2(
                item_id=source.document.item_id,
                fact_id=anchor.fact_id,
                start=start,
                end=end,
                text=source.body[start:end],
            )
        )
    return tuple(result)


def coalesced_contexts(source: GroundedSource) -> tuple[SourceContextSpanV2, ...]:
    """Send each overlapping source window once; no extra source positions are added."""
    merged: list[SourceContextSpanV2] = []
    for binding in sorted(contexts(source), key=lambda b: (b.start, b.end, str(b.fact_id))):
        if merged and binding.start <= merged[-1].end:
            previous = merged.pop()
            end = max(previous.end, binding.end)
            merged.append(
                previous.model_copy(
                    update={
                        "end": end,
                        "text": source.body[previous.start : end],
                        "fact_ids": (*previous.fact_ids, binding.fact_id),
                    }
                )
            )
        else:
            merged.append(
                SourceContextSpanV2(
                    item_id=binding.item_id,
                    fact_ids=(binding.fact_id,),
                    start=binding.start,
                    end=binding.end,
                    text=binding.text,
                )
            )
    return tuple(merged)


def validate_semantic_profiles(
    value: DiscoverySemanticProfilesV2, sources: Mapping[UUID, GroundedSource]
) -> None:
    if len(value.profiles) != len(sources) or {p.item_id for p in value.profiles} != set(sources):
        raise EditorialError("DISCOVERY_PRODUCT_SET_MISMATCH")
    for profile in value.profiles:
        source = sources[profile.item_id]
        product = primary_product(source)
        for judgment in (
            profile.role,
            profile.purpose,
            profile.targets,
            profile.method,
            profile.results,
        ):
            if judgment is None:
                continue
            if not set(judgment.fact_ids) <= set(source.anchors):
                raise EditorialError("DISCOVERY_OTHER_PRODUCT_GROUNDING")
            anchors = [source.anchors[key] for key in judgment.fact_ids]
            for anchor in anchors:
                validate_anchor(anchor, {profile.item_id: source})
            if not numbers(judgment.text) <= numbers(" ".join(a.quote for a in anchors)):
                raise EditorialError("DISCOVERY_UNSUPPORTED_NUMBER")
        if profile.role is not None:
            if product.identity.fact_id not in profile.role.fact_ids:
                raise EditorialError("DISCOVERY_REASON_IDENTITY_REQUIRED")
            if not any(
                f.fact_id in profile.role.fact_ids
                and f.fact_type not in {"product", "organization"}
                for f in source.evidence.verified_facts
            ):
                raise EditorialError("DISCOVERY_REASON_FUNCTION_REQUIRED")
            if product.name.split("\uff08", 1)[0].casefold() not in profile.role.text.casefold():
                raise EditorialError("DISCOVERY_REASON_PRODUCT_MISMATCH")


def validate_group_selection(
    value: DiscoveryGroupSelectionV2,
    sources: Mapping[UUID, GroundedSource],
    request: ComparisonDiscoveryRequestV2,
) -> None:
    if len(value.groups) > request.maximum_groups:
        raise EditorialError("DISCOVERY_HYPOTHESIS_BUDGET_EXCEEDED")
    seen: set[frozenset[UUID]] = set()
    selected: set[UUID] = set()
    for group in value.groups:
        ids = set(group.item_ids)
        if (
            len(ids) != 3
            or request.seed_item_id not in ids
            or not ids <= set(sources)
            or frozenset(ids) in seen
            or any(ids == set(group) for group in request.excluded_group_item_ids)
        ):
            raise EditorialError("DISCOVERY_PRODUCT_SET_MISMATCH")
        seen.add(frozenset(ids))
        selected.update(ids)
        own = {key: sources[key] for key in group.item_ids}
        if len({primary_product(s).product_key for s in own.values()}) != 3:
            raise EditorialError("DISCOVERY_THREE_DISTINCT_PRODUCTS_REQUIRED")
        if {r.item_id for r in group.product_reasons} != ids:
            raise EditorialError("DISCOVERY_PRODUCT_SET_MISMATCH")
        allowed = {key: anchor for source in own.values() for key, anchor in source.anchors.items()}
        for judgment in (group.selection_task, *(r.judgment for r in group.product_reasons)):
            if not set(judgment.fact_ids) <= set(allowed):
                raise EditorialError("DISCOVERY_FACT_REFERENCE_INVALID")
            anchors = [allowed[key] for key in judgment.fact_ids]
            for anchor in anchors:
                validate_anchor(anchor, own)
            if not numbers(judgment.text) <= numbers(" ".join(a.quote for a in anchors)):
                raise EditorialError("DISCOVERY_UNSUPPORTED_NUMBER")
        for reason in group.product_reasons:
            source = own[reason.item_id]
            product = primary_product(source)
            refs = set(reason.judgment.fact_ids)
            if not refs <= set(source.anchors):
                raise EditorialError("DISCOVERY_OTHER_PRODUCT_GROUNDING")
            if product.identity.fact_id not in refs:
                raise EditorialError("DISCOVERY_REASON_IDENTITY_REQUIRED")
            if not any(
                f.fact_id in refs and f.fact_type not in {"product", "organization"}
                for f in source.evidence.verified_facts
            ):
                raise EditorialError("DISCOVERY_REASON_FUNCTION_REQUIRED")
            if product.name.split("\uff08", 1)[0].casefold() not in reason.judgment.text.casefold():
                raise EditorialError("DISCOVERY_REASON_PRODUCT_MISMATCH")
    if len(selected) > request.detailed_pool_size:
        raise EditorialError("DISCOVERY_HYPOTHESIS_BUDGET_EXCEEDED")


def validate_evidence_inventory(
    value: DiscoveryEvidenceInventoryV2, sources: Mapping[UUID, GroundedSource]
) -> None:
    issues: list[EditorialError] = []
    for index, dimension in enumerate(value.dimensions):
        if {s.item_id for s in dimension.supports} != set(sources):
            issues.append(
                EditorialError(
                    "DISCOVERY_PRODUCT_SET_MISMATCH", path=("dimensions", index, "supports")
                )
            )
            continue
        question = dimension.question.model_copy(update={"required": False})
        for cell_index, support in enumerate(dimension.supports):
            source = sources[support.item_id]
            product = primary_product(source)
            tentative = CandidateSuitabilityAIOutputV1(
                decision="needs_information",
                role_fit="unknown",
                purpose_fit="unknown",
                audience_fit="unknown",
                reason=GroundedJudgmentRefV1(
                    text=product.name, fact_ids=(product.identity.fact_id,)
                ),
                score=0,
                cells=(support.cell,),
                missing_question_keys=(),
                uncertainties=(),
            )
            try:
                validate_product_assessment(tentative, (question,), source)
            except EditorialError as exc:
                path = exc.path
                if len(path) >= 2 and path[0] == "cells":
                    path = ("cell", *path[2:])
                issues.append(
                    EditorialError(
                        exc.code, path=("dimensions", index, "supports", cell_index, *path)
                    )
                )
    if issues:
        raise EditorialBatchError(tuple(issues))


def validate_hypothesis(
    value: ComparisonHypothesisOutputV2,
    sources: Mapping[UUID, GroundedSource],
    *,
    require_support: bool = False,
) -> None:
    if {r.item_id for r in value.product_reasons} != set(sources):
        raise EditorialError("DISCOVERY_PRODUCT_SET_MISMATCH")
    allowed = {key: anchor for source in sources.values() for key, anchor in source.anchors.items()}
    judgments: list[tuple[GroundedJudgmentRefV1, tuple[str | int, ...]]] = [
        (value.purpose, ("purpose",)),
        (value.audience, ("audience",)),
        *[
            (r.judgment, ("product_reasons", i, "judgment"))
            for i, r in enumerate(value.product_reasons)
        ],
    ]
    for judgment, path in judgments:
        if not set(judgment.fact_ids) <= set(allowed):
            raise EditorialError("DISCOVERY_FACT_REFERENCE_INVALID", path=(*path, "fact_ids"))
        anchors = [allowed[key] for key in judgment.fact_ids]
        for anchor in anchors:
            validate_anchor(anchor, sources)
        if not numbers(judgment.text) <= numbers(" ".join(a.quote for a in anchors)):
            raise EditorialError("DISCOVERY_UNSUPPORTED_NUMBER", path=(*path, "text"))
    for reason in value.product_reasons:
        source = sources[reason.item_id]
        product = primary_product(source)
        if not set(reason.judgment.fact_ids) <= set(source.anchors):
            raise EditorialError("DISCOVERY_OTHER_PRODUCT_GROUNDING")
        if product.identity.fact_id not in reason.judgment.fact_ids:
            raise EditorialError("DISCOVERY_REASON_IDENTITY_REQUIRED")
        if product.name.split("\uff08", 1)[0].casefold() not in reason.judgment.text.casefold():
            raise EditorialError("DISCOVERY_REASON_PRODUCT_MISMATCH")
    if require_support or value.question_support:
        required = {(key, q.key) for key in sources for q in value.questions}
        supplied = {(s.item_id, s.cell.question_key) for s in value.question_support}
        if supplied != required or len(supplied) != len(value.question_support):
            raise EditorialError("DISCOVERY_QUESTION_SUPPORT_REQUIRED")
        for key, source in sources.items():
            cells = tuple(s.cell for s in value.question_support if s.item_id == key)
            missing = tuple(
                q.key
                for q in value.questions
                if q.required
                and any(
                    c.question_key == q.key and c.status in {"unknown", "incomparable"}
                    for c in cells
                )
            )
            adoption = next(r.judgment for r in value.product_reasons if r.item_id == key)
            tentative = CandidateSuitabilityAIOutputV1(
                decision="needs_information" if missing else "eligible",
                role_fit="pass",
                purpose_fit="pass",
                audience_fit="pass",
                reason=adoption,
                score=0,
                cells=cells,
                missing_question_keys=missing,
                uncertainties=(),
            )
            try:
                validate_product_assessment(tentative, value.questions, source)
            except EditorialError as exc:
                path = exc.path
                if len(path) >= 2 and path[0] == "cells" and isinstance(path[1], int):
                    supports = [i for i, s in enumerate(value.question_support) if s.item_id == key]
                    path = ("question_support", supports[path[1]], "cell", *path[2:])
                elif path and path[0] == "reason":
                    index = next(i for i, r in enumerate(value.product_reasons) if r.item_id == key)
                    path = ("product_reasons", index, "judgment", *path[1:])
                raise EditorialError(exc.code, path=path) from exc
            if missing:
                index = next(
                    i
                    for i, s in enumerate(value.question_support)
                    if s.item_id == key and s.cell.question_key in missing
                )
                raise EditorialError(
                    "DISCOVERY_PROPOSED_MAJOR_UNSUPPORTED",
                    path=("question_support", index, "cell", "status"),
                )
        for question in value.questions:
            votes = {
                s.item_id
                for s in value.question_support
                if s.cell.question_key == question.key
                and s.cell.fact_ids
                and s.cell.status not in {"unknown", "incomparable"}
            }
            if len(votes) < 2:
                raise EditorialError("DISCOVERY_PROPOSED_MAJORITY_UNSUPPORTED")


def validate_review(value: DiscoveryReviewV2, sources: Mapping[UUID, GroundedSource]) -> None:
    allowed = {key for source in sources.values() for key in source.anchors}
    for check in value.checks:
        if not set(check.fact_ids) <= allowed:
            raise EditorialError("DISCOVERY_REVIEW_REFERENCE_INVALID")
        if check.result == "pass" and not check.fact_ids:
            raise EditorialError("DISCOVERY_REVIEW_GROUNDING_REQUIRED")


def group_issues(group: ComparisonGroupEvaluationV2) -> tuple[str, ...]:
    entries = group.evaluations
    issues = []
    if len(entries) != 3 or len({e.product.product_key for e in entries}) != 3:
        issues.append("DISCOVERY_THREE_DISTINCT_PRODUCTS_REQUIRED")
    docs = [d for e in entries for d in e.product.documents]
    if len({normalize_url(d.url) for d in docs}) < 3 or len({d.body_hash for d in docs}) < 3:
        issues.append("DISCOVERY_THREE_DISTINCT_SOURCES_REQUIRED")
    announcements = {d.announcement_key for d in docs if d.role == "announcement"}
    if len(announcements) != 3:
        issues.append("DISCOVERY_THREE_ANNOUNCEMENTS_REQUIRED")
    if any(e.evaluation.decision != "eligible" for e in entries):
        issues.append("DISCOVERY_INELIGIBLE_PRODUCT")
    for question in group.plan.hypothesis.questions:
        cells: list[tuple[str, ComparisonCellV1]] = []
        for entry in entries:
            cell = next((c for c in entry.evaluation.cells if c.question_key == question.key), None)
            if cell and cell.status not in {"unknown", "incomparable"} and cell.evidence:
                cells.append((entry.product.product_key, cell))
        if question.required and len({key for key, _ in cells}) != 3:
            issues.append("DISCOVERY_MAJOR_QUESTION_MISSING:" + question.key)
        if len({key for key, _ in cells}) < 2:
            issues.append("DISCOVERY_PRODUCT_MAJORITY_REQUIRED:" + question.key)
        cited = {a.item_id for _, cell in cells for a in cell.evidence}
        votes = {
            d.announcement_key for d in docs if d.role == "announcement" and d.item_id in cited
        }
        if len(votes) < 2:
            issues.append("DISCOVERY_ANNOUNCEMENT_MAJORITY_REQUIRED:" + question.key)
    return tuple(dict.fromkeys(issues))


def frozen_group(audit: ComparisonDiscoveryAuditV2) -> ComparisonGroupEvaluationV2:
    matches = [g for g in audit.groups if g.plan.hypothesis_id == audit.selected_hypothesis_id]
    if audit.outcome != "eligible" or len(matches) != 1 or not audit.frozen_hash:
        raise EditorialError("DISCOVERY_FROZEN_GROUP_REQUIRED")
    group = matches[0]
    if (
        not group.accepted
        or group.issues
        or group_issues(group)
        or group.independent is None
        or group.independent_ai_run_id is None
        or group.independent.blocking_issues
        or any(c.result != "pass" for c in group.independent.checks)
        or tuple(e.product for e in group.evaluations) != group.plan.products
        or audit.item_id not in {d.item_id for p in group.plan.products for d in p.documents}
    ):
        raise EditorialError("DISCOVERY_FROZEN_GROUP_REQUIRED")
    if canonical_payload_hash(group.model_dump(mode="json")) != audit.frozen_hash:
        raise EditorialError("DISCOVERY_FROZEN_HASH_MISMATCH")
    return group


def validate_product_assessment(
    value: CandidateSuitabilityAIOutputV1, questions: Any, source: GroundedSource
) -> None:
    bound = bind_candidate(value, source)
    product = primary_product(source)
    if not numbers(bound.reason.text) <= numbers(" ".join(a.quote for a in bound.reason.evidence)):
        raise EditorialError("DISCOVERY_REASON_UNSUPPORTED_NUMBER", path=("reason", "text"))
    if product.name.split("\uff08", 1)[0].casefold() not in bound.reason.text.casefold():
        raise EditorialError("DISCOVERY_REASON_PRODUCT_MISMATCH", path=("reason", "text"))
    keys = {q.key for q in questions}
    if len(bound.cells) != len(keys) or {c.question_key for c in bound.cells} != keys:
        raise EditorialError("DISCOVERY_QUESTION_SET_MISMATCH")
    missing = set()
    for index, cell in enumerate(bound.cells):
        if cell.status == "unknown":
            if cell.evidence:
                raise EditorialError(
                    "DISCOVERY_UNKNOWN_WITH_EVIDENCE", path=("cells", index, "fact_ids")
                )
        elif not cell.evidence:
            raise EditorialError(
                "DISCOVERY_CELL_GROUNDING_REQUIRED", path=("cells", index, "fact_ids")
            )
        quotes = " ".join(a.quote for a in cell.evidence)
        if not numbers(" ".join((cell.answer, *cell.conditions))) <= numbers(quotes):
            raise EditorialError(
                "DISCOVERY_CELL_UNSUPPORTED_NUMBER", path=("cells", index, "answer")
            )
        for field in ("plan", "version", "region", "as_of"):
            qualifier = getattr(cell, field)
            if qualifier and qualifier not in quotes:
                raise EditorialError(
                    "DISCOVERY_CELL_QUALIFIER_UNGROUNDED", path=("cells", index, field)
                )
        for anchor in cell.evidence:
            fact = next(f for f in source.evidence.verified_facts if f.fact_id == anchor.fact_id)
            preserved = " ".join((cell.answer, *cell.conditions))
            for condition in (
                fact.conditions,
                fact.region,
                fact.attribution,
                fact.unit,
                fact.currency,
            ):
                if condition and condition not in preserved:
                    raise EditorialError(
                        "DISCOVERY_CELL_CONDITION_LOST", path=("cells", index, "conditions")
                    )
            if fact.conditions and cell.status not in {
                "conditional",
                "planned",
                "incomparable",
            }:
                raise EditorialError(
                    "DISCOVERY_CELL_CONDITION_STATUS_INVALID", path=("cells", index, "status")
                )
        if cell.status in {"unknown", "incomparable"}:
            missing.add(cell.question_key)
    required_missing = missing & {q.key for q in questions if q.required}
    if set(bound.missing_question_keys) != required_missing:
        raise EditorialError("DISCOVERY_MISSING_QUESTIONS_MISMATCH")
    fits = (bound.role_fit, bound.purpose_fit, bound.audience_fit)
    if bound.decision == "eligible" and (required_missing or any(f != "pass" for f in fits)):
        raise EditorialError("DISCOVERY_REQUIRED_CONDITION_FAILED")
    if bound.decision == "needs_information" and "fail" in fits:
        raise EditorialError("DISCOVERY_REJECTED_ROLE_REQUIRED")
