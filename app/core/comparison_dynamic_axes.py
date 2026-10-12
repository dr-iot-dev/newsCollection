"""Deterministic identity, grounding and post-extraction majority checks."""

import re
from collections.abc import Mapping, Sequence
from uuid import UUID

from app.contracts.base import ContractModel
from app.contracts.comparison_dynamic_axes_v1 import (
    AxisCandidates,
    AxisCandidatesRef,
    AxisReview,
    AxisSelection,
    AxisValues,
    DynamicAxis,
)
from app.contracts.comparison_pair_discovery_v3 import PairDocument
from app.core.comparison_pair_discovery import (
    contains,
    norm,
    product_key,
    validate_product,
    validate_quotes,
)
from app.core.editorial import EditorialError, numbers, redact_contacts


def validate_documents(documents: Sequence[PairDocument]) -> None:
    if not 3 <= len(documents) <= 5:
        raise EditorialError("AXIS_GROUP_SIZE_INVALID")
    for values in (
        [d.item_id for d in documents],
        [d.url for d in documents],
        [d.body_hash for d in documents],
    ):
        if len(set(values)) != len(documents):
            raise EditorialError("AXIS_DUPLICATE_DOCUMENT")


GENERIC_SEARCH_FORMS = frozenset({"機能", "対応", "データ", "システム", "製品", "サービス"})
WEAK_SEARCH_FORMS = frozenset(
    {
        "警報",
        "検知",
        "超過",
        "安定して",
        "読み取る",
        "自動作成",
        "掲載",
        "回線",
        "読み取り",
        "更新",
        "一括",
        "複数の現場",
    }
)


def search_form_allowed(term: str, label: str) -> bool:
    form = norm(term)
    return (
        2 <= len(term) <= 24
        and form not in GENERIC_SEARCH_FORMS
        and not (form in WEAK_SEARCH_FORMS and form != norm(label))
        and not re.search(r"[()\[\]{}<>|「」『』【】〈〉《》]", form)
        and not re.search(r"\d+\s*(?:年|週間|日|円|ドル|か月|ヶ月|時間|台|%)", form)
        and not re.search(r"(?:できます|できる|しています|されます|します)$", form)
    )


def grounded_search_terms(
    value: AxisCandidatesRef, documents: Mapping[UUID, PairDocument]
) -> AxisCandidatesRef:
    """Keep only literal forms in each axis's referenced passages; never invent aliases."""
    resolved = resolve_evidence(value, documents, AxisCandidates)
    company_names = {
        name
        for doc in documents.values()
        for name in re.findall(r"株式会社\s*([A-Za-z][A-Za-z0-9_.-]*)", doc.body)
    }
    axes = []
    for ref, axis in zip(value.axes, resolved.axes, strict=True):
        terms: dict[str, str] = {}
        for term in ref.search_terms:
            if (
                any(contains(term, name) for name in company_names)
                and sum(contains(redact_contacts(doc.body), term) for doc in documents.values()) < 2
            ):
                continue
            if search_form_allowed(term, ref.label) and any(
                contains(quote.quote, term) for quote in axis.evidence
            ):
                terms.setdefault(norm(term), term)
        if not terms and any(contains(quote.quote, ref.label) for quote in axis.evidence):
            terms[norm(ref.label)] = ref.label
        # The validator rejects an axis with no grounded search form.
        axes.append(ref.model_copy(update={"search_terms": tuple(terms.values())}))
    return value.model_copy(update={"axes": tuple(axes)})


def matching_axis_terms(text: str, axes: Sequence[DynamicAxis]) -> dict[str, tuple[str, ...]]:
    """OR literal mentions, with NFKC/case folding and ASCII token boundaries; no AI."""
    result = {}
    for axis in axes:
        forms = dict.fromkeys((axis.label, *axis.search_terms))
        hits = tuple(term for term in forms if contains(text, term))
        if hits:
            result[axis.axis_id] = hits
    return result


def shared_search_candidates(
    value: AxisCandidatesRef, documents: Mapping[UUID, PairDocument]
) -> AxisCandidatesRef:
    """Retain axes with literal mentions in at least two distinct input articles."""
    grounded = grounded_search_terms(value, documents)
    axes = resolve_evidence(grounded, documents, AxisCandidates).axes
    mentions = [matching_axis_terms(redact_contacts(d.body), axes) for d in documents.values()]
    keep = {a.axis_id for a in axes if sum(a.axis_id in hits for hits in mentions) >= 2}
    return grounded.model_copy(
        update={"axes": tuple(a for a in grounded.axes if a.axis_id in keep)}
    )


def validate_candidates(result: AxisCandidates, documents: Mapping[UUID, PairDocument]) -> None:
    if (
        len({a.axis_id for a in result.axes}) != len(result.axes)
        or len({norm(a.question) for a in result.axes}) != len(result.axes)
        or len({norm(a.label) for a in result.axes}) != len(result.axes)
    ):
        raise EditorialError("AXIS_DUPLICATE_QUESTION")
    for index, axis in enumerate(result.axes):
        label = norm(axis.label)
        if not 2 <= len(axis.label) <= 24 or re.search(r"[()\[\]{}<>「」『』【】〈〉《》]", label):
            raise EditorialError("AXIS_LABEL_NOT_SEARCHABLE", path=("axes", index, "label"))
        validate_quotes(axis.evidence, documents)
        forms = [norm(term) for term in axis.search_terms]
        if (
            not forms
            or len(set(forms)) != len(forms)
            or any(not search_form_allowed(term, axis.label) for term in axis.search_terms)
        ):
            raise EditorialError("AXIS_SEARCH_TERMS_INVALID", path=("axes", index, "search_terms"))
        if (
            sum(
                bool(matching_axis_terms(redact_contacts(doc.body), (axis,)))
                for doc in documents.values()
            )
            < 2
        ):
            raise EditorialError("AXIS_SEARCH_NOT_SHARED", path=("axes", index, "search_terms"))
        for term_index, term in enumerate(axis.search_terms):
            if not any(contains(ref.quote, term) for ref in axis.evidence):
                raise EditorialError(
                    "AXIS_SEARCH_TERM_UNGROUNDED", path=("axes", index, "search_terms", term_index)
                )


def validate_values(
    result: AxisValues, document: PairDocument, axes: Sequence[DynamicAxis]
) -> None:
    validate_quotes(result.product.evidence, {document.item_id: document})
    identity_quotes = " ".join(q.quote for q in result.product.evidence)
    for field in ("name", "organization"):
        if getattr(result.product, field) not in identity_quotes:
            raise EditorialError("PAIR_PRODUCT_UNGROUNDED", path=("product", field))
    validate_product(result.product, document)
    if len(result.cells) != len(axes) or {c.axis_id for c in result.cells} != {
        a.axis_id for a in axes
    }:
        raise EditorialError("AXIS_CELL_SET_INVALID")
    for cell in result.cells:
        validate_quotes(cell.evidence, {document.item_id: document})
        if cell.status == "unknown":
            if cell.answer.strip() or cell.evidence or cell.conditions.strip():
                raise EditorialError("AXIS_UNKNOWN_WITH_VALUE")
        elif cell.status != "incomparable" and (not cell.evidence or not cell.answer.strip()):
            raise EditorialError("AXIS_CELL_UNGROUNDED")
        raw = " ".join(ref.quote for ref in cell.evidence)
        if not numbers(cell.answer + " " + cell.conditions) <= numbers(raw):
            raise EditorialError("PAIR_UNSUPPORTED_NUMBER")


def axis_coverage(values: Sequence[AxisValues], axes: Sequence[DynamicAxis]) -> dict[str, int]:
    if len({v.product.item_id for v in values}) != len(values) or len(
        {product_key(v.product) for v in values}
    ) != len(values):
        raise EditorialError("AXIS_DUPLICATE_PRODUCT")
    return {
        axis.axis_id: sum(
            any(
                c.axis_id == axis.axis_id
                and c.status not in {"unknown", "incomparable"}
                and bool(c.answer.strip())
                and bool(c.evidence)
                for c in value.cells
            )
            for value in values
        )
        for axis in axes
    }


def validate_selection(
    result: AxisSelection, axes: Sequence[DynamicAxis], counts: Mapping[str, int], size: int
) -> None:
    expected = {a.axis_id for a in axes}
    if (
        len(result.assessments) != len(expected)
        or {a.axis_id for a in result.assessments} != expected
    ):
        raise EditorialError("AXIS_ASSESSMENT_SET_INVALID")
    selected = result.selected_axis_ids
    if len(set(selected)) != len(selected) or not set(selected) <= expected:
        raise EditorialError("AXIS_SELECTION_SET_INVALID")
    assessments = {a.axis_id: a for a in result.assessments}
    if any(
        counts[key] < size // 2 + 1
        or not all(
            (
                assessments[key].answers_fit_question,
                assessments[key].useful,
                assessments[key].distinct,
            )
        )
        for key in selected
    ):
        raise EditorialError("AXIS_SELECTION_UNSUPPORTED")


def validate_review(result: AxisReview, selected: Sequence[str]) -> None:
    if len(result.checks) != len(selected) or {c.axis_id for c in result.checks} != set(selected):
        raise EditorialError("AXIS_REVIEW_SET_INVALID")


def review_passes(result: AxisReview) -> bool:
    return result.same_selection_task and all(
        all(
            (
                check.answers_fit_question,
                check.evidence_valid,
                check.conditions_preserved,
                check.useful,
                check.distinct,
            )
        )
        for check in result.checks
    )


def source_passages(document: PairDocument) -> list[dict[str, str | int]]:
    """Stable original paragraph references, excluding contact-bearing passages."""
    return [
        {
            "passage_id": f"p{index:04d}",
            "start": match.start(),
            "end": match.end(),
            "quote": match[0],
        }
        for index, match in enumerate(re.finditer(r"[^\n]+", document.body))
        if redact_contacts(match[0]) == match[0]
    ]


def resolve_evidence[T: ContractModel](
    value: ContractModel, documents: Mapping[UUID, PairDocument], model: type[T]
) -> T:
    """Resolve IDs to exact source quotes; never ask the model to copy offsets or quotes."""
    passages = {
        (doc.item_id, str(p["passage_id"])): p
        for doc in documents.values()
        for p in source_passages(doc)
    }
    data = value.model_dump(mode="json")

    def visit(node: object, path: tuple[str | int, ...] = ()) -> None:
        if isinstance(node, dict):
            if set(node) == {"item_id", "passage_id"}:
                key = (UUID(node["item_id"]), node["passage_id"])
                if key not in passages:
                    raise EditorialError("AXIS_PASSAGE_INVALID", path=path)
                passage = passages[key]
                del node["passage_id"]
                node.update(start=passage["start"], end=passage["end"], quote=passage["quote"])
            else:
                for key, child in node.items():
                    visit(child, (*path, key))
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, (*path, index))

    visit(data)
    return model.model_validate(data)
