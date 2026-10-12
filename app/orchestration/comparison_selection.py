"""Append-only shadow evaluation; never creates drafts or changes workflow state.

The CLI owns a dedicated session. With checkpoint=True each completed stage is
committed so an interrupted evaluation can reuse valid, hash-matched results.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.runner import AIRunner
from app.contracts.base import ContractModel
from app.contracts.comparison_selection_ai_v1 import (
    CandidateSuitabilityAIOutputV1,
    ComparisonPlanAIOutputV1,
)
from app.contracts.comparison_selection_v1 import (
    POLICY_VERSION,
    CandidateEvaluationV1,
    ComparedProductV1,
    ComparisonPlanV1,
    ComparisonSelectionAuditV1,
    ComparisonStageRecordV1,
    ComparisonSuitabilityOutputV1,
    GroundingV1,
    ProductDocumentV1,
    SourceExclusionBaselineV1,
)
from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.contracts.evidence_v1 import EvidencePackageV1
from app.core.comparison_selection import (
    GroundedSource,
    bind_candidate,
    bind_plan,
    choose_group,
    excluded,
    group_issues,
    primary_product,
    validate_anchor,
    validate_candidate,
    validate_independent,
    validate_plan,
)
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    AiRun,
    EvidencePackage,
    ExtractionResult,
    Fact,
    Item,
    ModuleMessage,
)
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.orchestration.editorial import checked_payload, eligible, latest

T = TypeVar("T", bound=ContractModel)


class ComparisonSelectionService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        runner: AIRunner | None = None,
        *,
        checkpoint: bool = False,
    ) -> None:
        self.session = session
        self.settings = settings
        self.runner = runner or AIRunner(session, settings)
        self.checkpoint = checkpoint

    def record(self, payload: ContractModel, consumer: str) -> ModuleMessage:
        row = ModuleMessageRepository(self.session).enqueue_once(
            ContractEnvelope.build(
                payload,
                contract_type=type(payload).__name__,
                producer="comparison_selection",
                producer_version="0.4.0",
            ),
            consumer=consumer,
            status="processed",
        )
        if row.processed_at is None:
            row.processed_at = datetime.now(UTC)
        self.session.flush()
        if self.checkpoint:
            self.session.commit()
        return row

    def source(self, item_id: UUID) -> GroundedSource:
        item = self.session.get(Item, item_id)
        if item is None:
            raise EditorialError("COMPARISON_ITEM_NOT_FOUND")
        eligible(self.session, item)
        extraction = self.session.scalar(
            select(ExtractionResult).where(
                ExtractionResult.item_id == item.id,
                ExtractionResult.revision == item.version,
            )
        )
        evidence_row = latest(self.session, EvidencePackage, item.id)
        if extraction is None or evidence_row is None or evidence_row.item_version != item.version:
            raise EditorialError("CURRENT_FACTS_REQUIRED")
        content = checked_payload(extraction, NormalizedContentV1)
        evidence = checked_payload(evidence_row, EvidencePackageV1)
        if content.quality_score < 0.6 or evidence.rights_blocked:
            raise EditorialError("COMPARISON_SOURCE_NOT_ELIGIBLE")
        anchors = {}
        for verified in evidence.verified_facts:
            fact = self.session.get(Fact, verified.fact_id)
            if (
                fact is None
                or fact.evidence_package_id != evidence_row.id
                or fact.item_id != item.id
                or fact.item_version != item.version
                or fact.evidence_id != verified.evidence_id
                or fact.normalized_value != verified.value
                or fact.evidence_start is None
                or fact.evidence_end is None
            ):
                raise EditorialError("COMPARISON_GROUNDING_INVALID")
            anchors[fact.id] = GroundingV1(
                item_id=item.id,
                fact_id=fact.id,
                evidence_id=verified.evidence_id,
                start=fact.evidence_start,
                end=fact.evidence_end,
                quote=fact.evidence_text,
            )
        source = GroundedSource(
            document=ProductDocumentV1(
                item_id=item.id,
                item_version=item.version,
                url=str(content.canonical_url),
                extraction_hash=extraction.payload_hash,
                evidence_hash=evidence_row.payload_hash,
                body_hash=content.body_sha256,
                announcement_key=content.body_sha256,
                role="announcement",
            ),
            body=content.body,
            evidence=evidence,
            anchors=anchors,
        )
        for anchor in anchors.values():
            validate_anchor(anchor, {item.id: source})
        return source

    @staticmethod
    def source_data(source: GroundedSource) -> dict[str, Any]:
        # Exact, verified source excerpts provide raw grounding without forwarding
        # contacts or entire source documents to every AI stage.
        return {
            "document": source.document.model_dump(mode="json"),
            "title": source.evidence.title,
            "facts": [f.model_dump(mode="json") for f in source.evidence.verified_facts],
            "grounding": [a.model_dump(mode="json") for a in source.anchors.values()],
            "uncertainties": source.evidence.uncertainties,
        }

    def stage(
        self,
        stage: Literal["plan", "candidate", "independent"],
        role: str,
        item_id: UUID,
        data: dict[str, Any],
        model: type[T],
        validate: Callable[[T], None],
    ) -> tuple[T, UUID, str]:
        fingerprint = self.runner.profile(role).fingerprint
        identity = canonical_payload_hash(
            {
                "data": data,
                "profile": fingerprint,
                "policy": POLICY_VERSION,
                "schema": model.model_json_schema(),
            }
        )
        rows = self.session.scalars(
            select(ModuleMessage).where(
                ModuleMessage.consumer == "comparison_selection_stage",
                ModuleMessage.payload_json["input_hash"].as_string() == identity,
            )
        )
        for row in rows:
            record = checked_payload(row, ComparisonStageRecordV1)
            run = self.session.get(AiRun, record.ai_run_id)
            if (
                record.stage != stage
                or record.item_id != item_id
                or record.policy_version != POLICY_VERSION
                or run is None
                or run.validation_status != "valid"
                or run.execution_role != role
            ):
                continue
            cached = model.model_validate(record.output_json)
            validate(cached)
            return cached, record.ai_run_id, identity
        result, run_id = self.runner.run(role, item_id, data, model, validate=validate, repair=True)
        if result is None or run_id is None:
            raise EditorialError("COMPARISON_AI_OUTPUT_INVALID")
        self.record(
            ComparisonStageRecordV1(
                item_id=item_id,
                input_hash=identity,
                stage=stage,
                ai_run_id=run_id,
                output_json=result.model_dump(mode="json"),
            ),
            "comparison_selection_stage",
        )
        return result, run_id, identity

    def plan(self, source: GroundedSource, editorial_intent: str | None = None) -> ComparisonPlanV1:
        result, run_id, identity = self.stage(
            "plan",
            "comparison_plan",
            source.document.item_id,
            {
                "source": self.source_data(source),
                **({"editorial_intent": editorial_intent} if editorial_intent is not None else {}),
            },
            ComparisonPlanAIOutputV1,
            lambda value: validate_plan(bind_plan(value, source), source),
        )
        rows = list(
            self.session.scalars(
                select(ModuleMessage).where(
                    ModuleMessage.consumer == "comparison_selection_plan",
                    ModuleMessage.payload_json["item_id"].as_string()
                    == str(source.document.item_id),
                )
            )
        )
        for row in rows:
            saved = cast(ComparisonPlanV1, checked_payload(row, ComparisonPlanV1))
            if saved.input_hash == identity:
                return saved
        plan = ComparisonPlanV1(
            plan_id=uuid5(NAMESPACE_URL, identity),
            item_id=source.document.item_id,
            item_version=source.document.item_version,
            revision=max((r.payload_json["revision"] for r in rows), default=0) + 1,
            input_hash=identity,
            extraction_hash=source.document.extraction_hash,
            evidence_hash=source.document.evidence_hash,
            ai_run_id=run_id,
            plan=bind_plan(result, source),
            editorial_intent=editorial_intent,
        )
        self.record(plan, "comparison_selection_plan")
        return plan

    def evaluate(
        self,
        item_id: UUID,
        candidate_ids: tuple[UUID, ...],
        baseline: SourceExclusionBaselineV1 | None = None,
        *,
        editorial_intent: str | None = None,
    ) -> ComparisonSelectionAuditV1:
        if editorial_intent is not None and not 1 <= len(editorial_intent) <= 2000:
            raise EditorialError("COMPARISON_EDITORIAL_INTENT_INVALID")
        if self.settings.comparison_selection_mode != "shadow":
            raise EditorialError("COMPARISON_SHADOW_MODE_REQUIRED")
        planner = self.runner.profile("comparison_plan").model
        assessor = self.runner.profile("comparison_assess").model
        verifier = self.runner.profile("comparison_verify").model
        if not planner or not assessor or not verifier:
            raise EditorialError("COMPARISON_MODELS_NOT_CONFIGURED")
        if verifier in {planner, assessor}:
            raise EditorialError("COMPARISON_INDEPENDENT_MODEL_REQUIRED")
        if len(candidate_ids) > self.settings.comparison_max_evaluations:
            raise EditorialError("COMPARISON_EVALUATION_BUDGET_EXCEEDED")
        if item_id in candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
            raise EditorialError("COMPARISON_DUPLICATE_ITEM")
        target = self.source(item_id)
        if excluded(target, baseline):
            raise EditorialError("COMPARISON_SOURCE_ALREADY_USED")
        plan = self.plan(target, editorial_intent)
        if plan.plan.context_status != "ready":
            audit = ComparisonSelectionAuditV1(
                item_id=item_id,
                input_hash=canonical_payload_hash(
                    {"plan": plan.input_hash, "outcome": "missing_plan_information"}
                ),
                plan=plan,
                exclusion_baseline=baseline,
                evaluations=(),
                selected_product_keys=(),
                outcome="deferred",
                reason_codes=("COMPARISON_PLAN_INFORMATION_REQUIRED",),
                missing_question_keys=tuple(q.key for q in plan.plan.questions if q.required),
                minimum_products=self.settings.comparison_min_products,
                minimum_sources=self.settings.comparison_min_sources,
            )
            self.record(audit, "comparison_selection_audit")
            return audit
        sources = {item_id: target}
        reasons = []
        for key in candidate_ids:
            try:
                source = self.source(key)
                if excluded(source, baseline):
                    reasons.append("COMPARISON_SOURCE_ALREADY_USED:" + str(key))
                else:
                    sources[key] = source
            except EditorialError as exc:
                reasons.append(exc.code + ":" + str(key))
        evaluations = []
        for source in sources.values():
            product = primary_product(source)
            result, run_id, identity = self.stage(
                "candidate",
                "comparison_assess",
                item_id,
                {
                    "plan": plan.model_dump(mode="json"),
                    "source": self.source_data(source),
                    "candidate_product_name": product.name,
                    "fact_constraints": [
                        {
                            "fact_id": str(f.fact_id),
                            "literal_qualifiers": [
                                str(value)
                                for value in (
                                    f.conditions,
                                    f.region,
                                    f.attribution,
                                    f.unit,
                                    f.currency,
                                )
                                if value
                            ],
                            "requires_conditional_status": bool(f.conditions),
                        }
                        for f in source.evidence.verified_facts
                        if any((f.conditions, f.region, f.attribution, f.unit, f.currency))
                    ],
                    "comparison_target_product_name": plan.plan.product.text,
                    "selection_task": plan.plan.selection_question,
                    "exclusion": baseline.model_dump(mode="json") if baseline else None,
                },
                CandidateSuitabilityAIOutputV1,
                self.candidate_validator(plan, product, source, sources),
            )
            evaluation = CandidateEvaluationV1(
                plan_id=plan.plan_id,
                input_hash=identity,
                product=product,
                ai_run_id=run_id,
                evaluation=bind_candidate(result, source),
            )
            self.record(evaluation, "comparison_selection_candidate")
            evaluations.append(evaluation)
        group = choose_group(
            plan.plan,
            evaluations[0],
            evaluations[1:],
            self.settings.comparison_min_products,
            self.settings.comparison_min_sources,
        )
        independent, independent_run = None, None
        if group:
            independent, independent_run, _ = self.stage(
                "independent",
                "comparison_verify",
                item_id,
                {
                    "plan": plan.model_dump(mode="json"),
                    "group": [e.model_dump(mode="json") for e in group],
                    "sources": [
                        self.source_data(sources[d.item_id])
                        for e in group
                        for d in e.product.documents
                    ],
                    "minimum_products": self.settings.comparison_min_products,
                    "minimum_sources": self.settings.comparison_min_sources,
                },
                ComparisonSuitabilityOutputV1,
                lambda value: validate_independent(value, group, sources),
            )
            if independent.blocking_issues or any(c.result != "pass" for c in independent.checks):
                reasons.append("COMPARISON_INDEPENDENT_REVIEW_FAILED")
        else:
            reasons.append("COMPARISON_NO_SUITABLE_GROUP")
            reasons.extend(
                group_issues(
                    plan.plan,
                    evaluations,
                    self.settings.comparison_min_products,
                    self.settings.comparison_min_sources,
                )
            )
        missing = tuple(
            dict.fromkeys(q for e in evaluations for q in e.evaluation.missing_question_keys)
        )
        audit = ComparisonSelectionAuditV1(
            item_id=item_id,
            input_hash=canonical_payload_hash(
                {
                    "plan": plan.input_hash,
                    "evaluations": [e.input_hash for e in evaluations],
                    "independent_run": independent_run,
                    "minimum_products": self.settings.comparison_min_products,
                    "minimum_sources": self.settings.comparison_min_sources,
                    "exclusion": baseline.model_dump(mode="json") if baseline else None,
                }
            ),
            plan=plan,
            evaluations=tuple(evaluations),
            exclusion_baseline=baseline,
            selected_product_keys=tuple(e.product.product_key for e in group),
            independent_ai_run_id=independent_run,
            independent=independent,
            outcome="eligible"
            if group and "COMPARISON_INDEPENDENT_REVIEW_FAILED" not in reasons
            else "deferred",
            reason_codes=tuple(dict.fromkeys(reasons)),
            missing_question_keys=missing,
            minimum_products=self.settings.comparison_min_products,
            minimum_sources=self.settings.comparison_min_sources,
        )
        self.record(audit, "comparison_selection_audit")
        return audit

    @staticmethod
    def candidate_validator(
        plan: ComparisonPlanV1,
        product: ComparedProductV1,
        source: GroundedSource,
        sources: dict[UUID, GroundedSource],
    ) -> Callable[[CandidateSuitabilityAIOutputV1], None]:
        def validate(value: CandidateSuitabilityAIOutputV1) -> None:
            validate_candidate(bind_candidate(value, source), plan.plan, product, sources)

        return validate
