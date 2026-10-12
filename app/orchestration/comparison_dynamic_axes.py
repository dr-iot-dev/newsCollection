"""Checkpointed shadow group analysis; produces comparison material, never publication."""

import csv
import json
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, TypeVar, cast
from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.ai.runner import AIRunner
from app.contracts.base import ContractModel
from app.contracts.comparison_dynamic_axes_v1 import (
    POLICY,
    SEARCH_POLICY,
    AxisCandidates,
    AxisCandidatesRef,
    AxisReview,
    AxisSelection,
    AxisValues,
    AxisValuesRef,
    DynamicAxesRequest,
    DynamicAxesState,
)
from app.contracts.comparison_pair_discovery_v3 import PairDocument
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.core.comparison_dynamic_axes import (
    axis_coverage,
    matching_axis_terms,
    resolve_evidence,
    review_passes,
    shared_search_candidates,
    source_passages,
    validate_candidates,
    validate_documents,
    validate_review,
    validate_selection,
    validate_values,
)
from app.core.comparison_pair_discovery import bind_quote_offsets, product_key, text_hash
from app.core.config import Settings
from app.core.editorial import EditorialError, redact_contacts
from app.infrastructure.db.models import (
    AiRun,
    ExtractionResult,
    Item,
    LegalStatus,
    ModuleMessage,
    Source,
)
from app.infrastructure.db.repositories.messages import ModuleMessageRepository

T = TypeVar("T", bound=ContractModel)
CONSUMER = "comparison_dynamic_axes"
ROLES = ("axis_discover", "axis_extract", "axis_repair", "axis_select", "axis_review")


def document_data(doc: PairDocument) -> dict[str, Any]:
    return {
        "item_id": str(doc.item_id),
        "title": doc.title,
        "url": doc.url,
        "body": redact_contacts(doc.body),
        "evidence_passages": [
            {"passage_id": p["passage_id"], "text": p["quote"]} for p in source_passages(doc)
        ],
    }


def load_documents(session: Session, item_ids: tuple[UUID, ...]) -> tuple[PairDocument, ...]:
    documents = []
    for item_id in item_ids:
        item = session.get(Item, item_id)
        if item is None:
            raise EditorialError("AXIS_ITEM_NOT_FOUND")
        source = session.get(Source, item.source_id)
        if source is None or not source.enabled or source.legal_status != LegalStatus.APPROVED:
            raise EditorialError("AXIS_SOURCE_NOT_APPROVED")
        if item.duplicate_of_id is not None:
            raise EditorialError("AXIS_DUPLICATE_DOCUMENT")
        extraction = session.scalar(
            select(ExtractionResult).where(
                ExtractionResult.item_id == item_id, ExtractionResult.revision == item.version
            )
        )
        if extraction is None:
            raise EditorialError("EXTRACTION_REQUIRED")
        payload = extraction.payload_json
        documents.append(
            PairDocument(
                item_id=item.id,
                item_version=item.version,
                snapshot_id=UUID(payload["snapshot_id"]),
                source_id=item.source_id,
                url=item.canonical_url,
                title=payload["title"],
                body=payload["body"],
                body_hash=text_hash(payload["body"]),
            )
        )
    validate_documents(documents)
    return tuple(documents)


class DynamicAxesService:
    def __init__(
        self, session: Session, settings: Settings, runner: AIRunner | None = None
    ) -> None:
        self.session, self.settings = session, settings
        self.runner = runner or AIRunner(session, settings)
        self.state: DynamicAxesState | None = None
        self.row: ModuleMessage | None = None
        self.calls_left = 0

    def save(self, **changes: Any) -> None:
        assert self.state is not None and self.row is not None
        self.state = DynamicAxesState.model_validate(
            {**self.state.model_dump(mode="python"), **changes}
        )
        self.row.result_json = self.state.model_dump(mode="json")
        self.row.status = (
            "processed"
            if self.state.status in {"held", "selection_passed", "candidates_ready"}
            else "axis_checkpoint"
        )
        self.row.processed_at = datetime.now(UTC)
        self.session.commit()

    def reserve(self) -> None:
        assert self.state is not None
        if self.calls_left <= 0:
            raise EditorialError("AXIS_CALL_BUDGET")
        self.calls_left -= 1
        self.save(ai_calls=self.state.ai_calls + 1)

    def stage(
        self, role: str, data: dict[str, Any], model: type[T], validate: Callable[[T], None]
    ) -> T:
        assert self.state is not None
        identity = canonical_payload_hash(
            {
                "data": data,
                "profile": self.runner.profile(role).fingerprint,
                "schema": model.model_json_schema(),
                "policy": POLICY,
                "search_normalization": "evidence-literal-shared-v4",
            }
        )
        cached = self.state.stages.get(identity)
        if cached is not None:
            run = self.session.get(AiRun, UUID(cached["ai_run_id"]))
            input_hashes = {
                canonical_payload_hash(
                    {"data": data, "profile": self.runner.profile(role).fingerprint, "attempt": a}
                )
                for a in (0, 1)
            }
            if (
                run is None
                or run.validation_status != "valid"
                or run.execution_role != role
                or run.model != self.runner.profile(role).model
                or run.input_hash not in input_hashes
                or run.output_json != cached["output"]
            ):
                raise EditorialError("AXIS_AI_CACHE_INVALID")
            cached_result = model.model_validate(cached["output"])
            validate(cached_result)
            return cached_result
        start = len(self.runner.run_ids)
        documents = {d.item_id: d for d in self.state.request.documents}

        def normalize(value: T) -> T:
            bound = bind_quote_offsets(value, documents)
            if isinstance(bound, AxisCandidatesRef):
                return cast(T, shared_search_candidates(bound, documents))
            return bound

        try:
            result, run_id = self.runner.run(
                role,
                UUID(data["source"]["item_id"])
                if role in {"axis_extract", "axis_repair"}
                else (self.state.request.documents[0].item_id),
                data,
                model,
                validate=validate,
                normalize=normalize,
                repair=True,
                before_call=self.reserve,
            )
        finally:
            attempts = self.runner.run_ids[start:]
            if attempts:
                self.save(ai_run_ids=tuple(dict.fromkeys((*self.state.ai_run_ids, *attempts))))
        if result is None or run_id is None:
            raise EditorialError("AXIS_AI_OUTPUT_INVALID")
        self.save(
            stages={
                **self.state.stages,
                identity: {
                    "role": role,
                    "ai_run_id": str(run_id),
                    "output": result.model_dump(mode="json"),
                },
            }
        )
        return result

    def select_values(
        self,
        request: DynamicAxesRequest,
        candidates: AxisCandidates,
        values: tuple[AxisValues, ...],
        counts: dict[str, int],
        feedback: AxisReview | None = None,
    ) -> AxisSelection:
        data: dict[str, Any] = {
            "editorial_intent": request.editorial_intent,
            "axes": [a.model_dump(mode="json") for a in candidates.axes],
            "values": [v.model_dump(mode="json") for v in values],
            "coverage": counts,
            "strict_majority": len(values) // 2 + 1,
            "eligible_axis_ids": [
                key for key, count in counts.items() if count >= len(values) // 2 + 1
            ],
        }
        if feedback is not None:
            data["validation_feedback"] = feedback.model_dump(mode="json")
        return self.stage(
            "axis_select",
            data,
            AxisSelection,
            partial(validate_selection, axes=candidates.axes, counts=counts, size=len(values)),
        )

    def review_values(
        self,
        request: DynamicAxesRequest,
        candidates: AxisCandidates,
        values: tuple[AxisValues, ...],
        counts: dict[str, int],
        selection: AxisSelection,
        *,
        revision: int = 0,
    ) -> AxisReview:
        data: dict[str, Any] = {
            "editorial_intent": request.editorial_intent,
            "purpose": selection.purpose,
            "sources": [document_data(d) for d in request.documents],
            "axes": [
                a.model_dump(mode="json")
                for a in candidates.axes
                if a.axis_id in selection.selected_axis_ids
            ],
            "values": [
                {
                    "product": v.product.model_dump(mode="json"),
                    "cells": [
                        c.model_dump(mode="json")
                        for c in v.cells
                        if c.axis_id in selection.selected_axis_ids
                    ],
                }
                for v in values
            ],
            "coverage": {key: counts[key] for key in selection.selected_axis_ids},
            "strict_majority": len(values) // 2 + 1,
        }
        if revision:
            data["plan_revision"] = revision
        return self.stage(
            "axis_review",
            data,
            AxisReview,
            partial(validate_review, selected=selection.selected_axis_ids),
        )

    def repair_values(
        self,
        request: DynamicAxesRequest,
        candidates: AxisCandidates,
        values: tuple[AxisValues, ...],
        review: AxisReview,
    ) -> tuple[AxisValues, ...]:
        docs = {d.item_id: d for d in request.documents}
        previous = {v.product.item_id: v for v in values}
        repaired = []
        feedback = [
            c.model_dump(mode="json")
            for c in review.checks
            if not all(
                (
                    c.answers_fit_question,
                    c.evidence_valid,
                    c.conditions_preserved,
                    c.useful,
                    c.distinct,
                )
            )
        ]
        for doc in request.documents:
            old = previous[doc.item_id]

            def validate_repair(
                refs: AxisValuesRef,
                document: PairDocument = doc,
                prior: AxisValues = old,
            ) -> None:
                value = resolve_evidence(refs, docs, AxisValues)
                validate_values(value, document, candidates.axes)
                if product_key(value.product) != product_key(prior.product):
                    raise EditorialError("AXIS_PRODUCT_CHANGED")

            refs = self.stage(
                "axis_repair",
                {
                    "source": document_data(doc),
                    "axes": [
                        a.model_dump(mode="json", exclude={"evidence"}) for a in candidates.axes
                    ],
                    "previous_values": old.model_dump(mode="json"),
                    "validation_feedback": feedback,
                },
                AxisValuesRef,
                validate_repair,
            )
            repaired.append(resolve_evidence(refs, docs, AxisValues))
        return tuple(repaired)

    def run(self, request: DynamicAxesRequest, *, call_budget: int = 20) -> DynamicAxesState:
        validate_documents(request.documents)
        if call_budget < 1:
            raise EditorialError("AXIS_CALL_BUDGET")
        self.calls_left = call_budget
        bind = self.session.get_bind()
        lock = None
        key = int.from_bytes(request.run_id.bytes[:8], "big", signed=True)
        if bind.dialect.name == "postgresql":
            if not isinstance(bind, Engine):
                raise EditorialError("AXIS_DEDICATED_ENGINE_REQUIRED")
            lock = bind.connect()
            if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
                lock.close()
                raise EditorialError("AXIS_RUN_ALREADY_ACTIVE")
        try:
            return self._run(request)
        finally:
            if lock is not None:
                try:
                    lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    lock.commit()
                finally:
                    lock.close()

    def _run(self, request: DynamicAxesRequest) -> DynamicAxesState:
        active_roles = ("axis_discover",) if request.mode == "discovery_only" else ROLES
        fingerprint = canonical_payload_hash(
            {
                "policy": POLICY,
                "search_policy": SEARCH_POLICY,
                "search_normalization": "evidence-literal-shared-v4",
                "profiles": {role: self.runner.profile(role).fingerprint for role in active_roles},
                "schemas": [
                    m.model_json_schema()
                    for m in (AxisCandidatesRef, AxisValuesRef, AxisSelection, AxisReview)
                ],
                "input_limit": self.settings.ai_max_input_chars,
                "output_limit": self.settings.ai_max_output_tokens,
            }
        )
        row = self.session.get(ModuleMessage, request.run_id)
        if row is None:
            envelope = ContractEnvelope.build(
                request,
                contract_type="DynamicAxesRequest",
                producer="comparison_dynamic_axes",
                producer_version="0.5.0",
                correlation_id=request.run_id,
            ).model_copy(update={"message_id": request.run_id})
            row = ModuleMessageRepository(self.session).enqueue_once(envelope, consumer=CONSUMER)
        if (
            row.consumer != CONSUMER
            or row.payload_hash != canonical_payload_hash(request.model_dump(mode="json"))
            or row.payload_json != request.model_dump(mode="json")
        ):
            raise EditorialError("AXIS_REQUEST_MISMATCH")
        self.row = row
        self.state = (
            DynamicAxesState.model_validate(row.result_json)
            if row.result_json
            else (DynamicAxesState(request=request, fingerprint=fingerprint))
        )
        if (
            self.state.fingerprint != fingerprint
            or self.state.policy != POLICY
            or (self.state.request != request)
        ):
            raise EditorialError("AXIS_RESUME_CONFIGURATION_CHANGED")
        if self.state.status in {"held", "selection_passed", "candidates_ready"}:
            return self.state
        self.save(status="running", reason="")
        try:
            models = {role: self.runner.profile(role).model for role in ROLES}
            if request.mode != "discovery_only" and (
                not all(models.values())
                or models["axis_review"] in {models[r] for r in ROLES if r != "axis_review"}
            ):
                raise EditorialError("AXIS_INDEPENDENT_MODEL_REQUIRED")
            docs = {d.item_id: d for d in request.documents}
            candidate_refs = self.stage(
                "axis_discover",
                {"sources": [document_data(d) for d in request.documents]},
                AxisCandidatesRef,
                lambda value: validate_candidates(
                    resolve_evidence(value, docs, AxisCandidates), docs
                ),
            )
            candidates = resolve_evidence(candidate_refs, docs, AxisCandidates)
            self.save(candidates=candidates)
            if not candidates.axes:
                self.save(status="held", reason="no_candidate_axes")
                return self.state
            if request.mode == "discovery_only":
                self.save(status="candidates_ready", reason="discovery_only_completed")
                return self.state
            extracted_values = []
            for doc in request.documents:

                def validate_ref_values(value: AxisValuesRef, document: PairDocument = doc) -> None:
                    validate_values(
                        resolve_evidence(value, docs, AxisValues), document, candidates.axes
                    )

                refs = self.stage(
                    "axis_extract",
                    {
                        "source": document_data(doc),
                        "axes": [
                            a.model_dump(mode="json", exclude={"evidence"}) for a in candidates.axes
                        ],
                    },
                    AxisValuesRef,
                    validate_ref_values,
                )
                extracted_values.append(resolve_evidence(refs, docs, AxisValues))
            values = tuple(extracted_values)
            self.save(values=values)
            counts = axis_coverage(values, candidates.axes)
            self.save(coverage=counts)
            selection = self.select_values(request, candidates, values, counts)
            self.save(selection=selection)
            if (
                not selection.same_selection_task
                or len(selection.selected_axis_ids) < request.minimum_axes
            ):
                self.save(status="held", reason="selection_insufficient_or_group_unsuitable")
                return self.state
            review = self.review_values(request, candidates, values, counts, selection)
            needs_repair = review.same_selection_task and any(
                not all((c.answers_fit_question, c.evidence_valid, c.conditions_preserved))
                for c in review.checks
            )
            if not review_passes(review) and needs_repair:
                self.save(initial_review=review, repair_round=1)
                values = self.repair_values(request, candidates, values, review)
                counts = axis_coverage(values, candidates.axes)
                self.save(values=values, coverage=counts)
                selection = self.select_values(request, candidates, values, counts, review)
                self.save(selection=selection)
                if (
                    not selection.same_selection_task
                    or len(selection.selected_axis_ids) < request.minimum_axes
                ):
                    self.save(
                        status="held", reason="repair_selection_insufficient_or_group_unsuitable"
                    )
                    return self.state
                review = self.review_values(
                    request, candidates, values, counts, selection, revision=1
                )
            passed = review_passes(review)
            self.save(
                review=review,
                status="selection_passed" if passed else "held",
                reason="independent_review_passed" if passed else "independent_review_failed",
            )
        except EditorialError as exc:
            self.save(
                status="paused_budget"
                if exc.code == "AXIS_CALL_BUDGET"
                else ("held" if exc.code == "AXIS_DUPLICATE_PRODUCT" else "waiting_retry"),
                reason=exc.code,
            )
        return self.state


def load_request(session: Session, run_id: UUID) -> DynamicAxesRequest:
    row = session.get(ModuleMessage, run_id)
    if row is None or row.consumer != CONSUMER:
        raise EditorialError("AXIS_RUN_NOT_FOUND")
    return DynamicAxesRequest.model_validate(row.payload_json)


def export_run(session: Session, run_id: UUID, directory: Path) -> None:
    row = session.get(ModuleMessage, run_id)
    if row is None or row.consumer != CONSUMER or not row.result_json:
        raise EditorialError("AXIS_RUN_NOT_FOUND")
    state = DynamicAxesState.model_validate(row.result_json)
    existing_audit = directory / "audit.json"
    if (
        existing_audit.exists()
        and DynamicAxesState.model_validate_json(
            existing_audit.read_text(encoding="utf-8")
        ).request.run_id
        != run_id
    ):
        raise EditorialError("AXIS_EXPORT_RUN_MISMATCH")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "audit.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
    (directory / "candidates.json").write_text(
        state.candidates.model_dump_json(indent=2) if state.candidates else '{"axes": []}',
        encoding="utf-8",
    )
    runs = [session.get(AiRun, key) for key in state.ai_run_ids]
    (directory / "ai-runs.json").write_text(
        json.dumps(
            [
                {
                    "id": str(r.id),
                    "item_id": str(r.item_id),
                    "role": r.execution_role,
                    "prompt_version": r.prompt_version,
                    "input_hash": r.input_hash,
                    "model": r.model,
                    "validation": r.validation_status,
                    "errors": r.validation_errors_json,
                    "input_tokens": r.token_in,
                    "output_tokens": r.token_out,
                    "latency_ms": r.latency_ms,
                    "cost_estimate": str(r.cost_estimate)
                    if (r.cost_estimate is not None)
                    else None,
                }
                for r in runs
                if r is not None
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with (directory / "coverage.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("axis_id", "question", "layer", "products", "required", "selected"))
        for a in state.candidates.axes if state.candidates else ():
            writer.writerow(
                (
                    a.axis_id,
                    a.question,
                    a.layer,
                    state.coverage.get(a.axis_id, 0),
                    len(state.request.documents) // 2 + 1,
                    bool(state.selection and a.axis_id in state.selection.selected_axis_ids),
                )
            )
    metrics = {
        "status": state.status,
        "reason": state.reason,
        "ai_calls": state.ai_calls,
        "product_coverage": {
            str(v.product.item_id): sum(
                c.status not in {"unknown", "incomparable"} and bool(c.evidence)
                for c in v.cells
                if state.selection and (c.axis_id in state.selection.selected_axis_ids)
            )
            for v in state.values
        },
    }
    (directory / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    axes = state.candidates.axes if state.candidates else ()
    search = {
        "policy": SEARCH_POLICY,
        "match_kind": "literal_mention",
        "axes": [
            {"axis_id": a.axis_id, "label": a.label, "search_terms": a.search_terms} for a in axes
        ],
        "documents": [
            {
                "item_id": str(d.item_id),
                "matches": matching_axis_terms(redact_contacts(d.body), axes),
            }
            for d in state.request.documents
        ],
    }
    (directory / "axis-search.json").write_text(
        json.dumps(search, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if state.status != "selection_passed":
        return
    assert state.selection is not None and state.candidates is not None
    payload = {
        "policy": POLICY,
        "selection_only": True,
        "documents": [d.model_dump(mode="json") for d in state.request.documents],
        "purpose": state.selection.purpose,
        "axes": [
            a.model_dump(mode="json")
            for a in state.candidates.axes
            if (a.axis_id in state.selection.selected_axis_ids)
        ],
        "values": [
            {
                "product": v.product.model_dump(mode="json"),
                "cells": [
                    c.model_dump(mode="json")
                    for c in v.cells
                    if (c.axis_id in state.selection.selected_axis_ids)
                ],
            }
            for v in state.values
        ],
        "review": state.review.model_dump(mode="json") if state.review else None,
    }
    payload["frozen_hash"] = canonical_payload_hash(payload)
    (directory / "selection.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def cell_text(value: str) -> str:
        return value.replace("|", "/").replace("\n", " ")

    lines = [
        "| 比較項目 | " + " | ".join(cell_text(v.product.name) for v in state.values) + " |",
        "| --- | " + " | ".join("---" for _ in state.values) + " |",
    ]
    for axis in state.candidates.axes:
        if axis.axis_id not in state.selection.selected_axis_ids:
            continue
        cells = []
        for value in state.values:
            cell = next(c for c in value.cells if c.axis_id == axis.axis_id)
            status_label = {"planned": "提供予定: ", "conditional": "条件付き: "}.get(
                cell.status, ""
            )
            cells.append(
                cell_text(
                    "資料で確認できず"
                    if cell.status == "unknown"
                    else (
                        status_label
                        + cell.answer
                        + ("(" + cell.conditions + ")" if cell.conditions else "")
                    )
                )
            )
        lines.append("| " + cell_text(axis.question) + " | " + " | ".join(cells) + " |")
    lines.extend(["", *(f"- [{d.title}]({d.url})" for d in state.request.documents), ""])
    (directory / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
