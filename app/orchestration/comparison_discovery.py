"""Bounded, resumable joint exploration. No workflow promotion or delivery."""

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text

from app.contracts.base import ContractModel
from app.contracts.comparison_discovery_v2 import (
    POLICY_VERSION,
    ComparisonDiscoveryAuditV2,
    ComparisonDiscoveryRequestV2,
    ComparisonGroupEvaluationV2,
    ComparisonGroupProposalV2,
    ComparisonHypothesisV2,
    DiscoveryBudgetReservationV2,
    DiscoveryEvidenceInventoryV2,
    DiscoveryGroupPlanningV2,
    DiscoveryGroupRankingV2,
    DiscoveryGroupSelectionV2,
    DiscoveryProductEvaluationV2,
    DiscoveryReviewV2,
    DiscoverySemanticProfilesV2,
    DiscoveryStageRecordV2,
    ProductComparisonProfileV2,
    RetrievalCandidateSetV2,
)
from app.contracts.comparison_selection_ai_v1 import CandidateSuitabilityAIOutputV1
from app.contracts.comparison_selection_v1 import SourceExclusionBaselineV1
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.core.comparison_discovery import (
    coalesced_contexts,
    contexts,
    frozen_group,
    group_issues,
    normalize_judgment_references,
    validate_evidence_inventory,
    validate_group_selection,
    validate_hypothesis,
    validate_product_assessment,
    validate_review,
    validate_semantic_profiles,
)
from app.core.comparison_selection import GroundedSource, bind_candidate, excluded, primary_product
from app.core.editorial import INJECTION, EditorialError, redact_contacts
from app.infrastructure.comparison_retrieval import rank_candidates, rank_seeded_groups
from app.infrastructure.db.models import AiRun, Item, ModuleMessage
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.orchestration.comparison_selection import ComparisonSelectionService
from app.orchestration.editorial import checked_payload

T = TypeVar("T", bound=ContractModel)


class ComparisonDiscoveryService(ComparisonSelectionService):
    request_hash: str
    request: ComparisonDiscoveryRequestV2

    def source(self, item_id: UUID) -> GroundedSource:
        source = super().source(item_id)
        if INJECTION.search(source.body):
            raise EditorialError("PROMPT_INJECTION_SUSPECTED")
        return source

    def record(self, payload: ContractModel, consumer: str) -> ModuleMessage:
        row = ModuleMessageRepository(self.session).enqueue_once(
            ContractEnvelope.build(
                payload,
                contract_type=type(payload).__name__,
                producer="comparison_discovery",
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

    def used_calls(self) -> int:
        predicate = (
            ModuleMessage.payload_json["budget_id"].as_string() == str(self.request.budget_id)
            if self.request.budget_id
            else ModuleMessage.payload_json["request_hash"].as_string() == self.request_hash
        )
        rows = list(
            self.session.scalars(
                select(ModuleMessage).where(
                    ModuleMessage.consumer == "comparison_discovery_budget",
                    predicate,
                )
            )
        )
        for row in rows:
            checked_payload(row, DiscoveryBudgetReservationV2)
        return len(rows)

    def reserve(self, input_hash: str) -> None:
        # Reserve atomically across workers. The dedicated checkpointing CLI commits
        # the previous attempt before acquiring a short reservation transaction.
        if self.checkpoint:
            self.session.commit()
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            scope = str(self.request.budget_id or self.request_hash)
            lock_key = int.from_bytes(sha256(scope.encode()).digest()[:8], signed=True)
            self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        elif dialect == "sqlite" and self.checkpoint:
            self.session.execute(text("BEGIN IMMEDIATE"))
        used = self.used_calls()
        if used >= self.request.maximum_api_calls:
            raise EditorialError("DISCOVERY_API_BUDGET_EXHAUSTED")
        self.record(
            DiscoveryBudgetReservationV2(
                item_id=self.request.seed_item_id,
                request_hash=self.request_hash,
                budget_id=self.request.budget_id,
                ordinal=used + 1,
                input_hash=input_hash,
            ),
            "comparison_discovery_budget",
        )

    def discovery_stage(
        self,
        role: str,
        item_id: UUID,
        data: dict[str, Any],
        model: type[T],
        validate: Callable[[T], None],
    ) -> tuple[T, UUID, str]:
        # A changed search/call budget does not change a completed stage's evidence.
        # Substantive inputs, schema and the actual model profile determine reuse.
        data = {**data, "policy": POLICY_VERSION}
        profile = self.runner.profile(role)
        identity = canonical_payload_hash(
            {
                "data": data,
                "profile": profile.fingerprint,
                "policy": POLICY_VERSION,
                "schema": model.model_json_schema(),
            }
        )
        hashes = [
            canonical_payload_hash(
                {"data": data, "profile": profile.fingerprint, "attempt": attempt}
            )
            for attempt in range(2)
        ]
        rows = self.session.scalars(
            select(ModuleMessage).where(
                ModuleMessage.consumer == "comparison_discovery_stage",
                ModuleMessage.payload_json["input_hash"].as_string() == identity,
            )
        )
        for row in rows:
            saved = checked_payload(row, DiscoveryStageRecordV2)
            run = self.session.get(AiRun, saved.ai_run_id)
            if (
                saved.role != role
                or saved.item_id != item_id
                or run is None
                or run.execution_role != role
                or run.item_id != item_id
                or run.model != profile.model
                or run.provider != profile.provider
                or run.model_profile_key != profile.key
                or run.prompt_version != profile.prompt_version
                or run.input_hash not in hashes
                or run.validation_status != "valid"
                or run.output_json != saved.output_json
            ):
                raise EditorialError("DISCOVERY_STAGE_RECORD_INVALID")
            cached = model.model_validate(saved.output_json)
            validate(cached)
            return cached, saved.ai_run_id, identity
        # Both invalid outputs and interrupted running calls consume attempts. Never
        # repeat an identical failed stage until it eventually happens to pass.
        if self.session.scalar(select(AiRun.id).where(AiRun.input_hash.in_(hashes))):
            raise EditorialError("DISCOVERY_STAGE_PREVIOUSLY_INCOMPLETE")
        value, run_id = self.runner.run(
            role,
            item_id,
            data,
            model,
            validate=validate,
            normalize=partial(
                normalize_judgment_references,
                allowed_fact_ids={
                    UUID(f["fact_id"])
                    for source in data.get("sources", data.get("catalog", [data.get("source", {})]))
                    for f in source.get("facts", [])
                },
            ),
            repair=True,
            before_call=lambda: self.reserve(identity),
        )
        if value is None or run_id is None:
            raise EditorialError("DISCOVERY_AI_OUTPUT_INVALID")
        self.record(
            DiscoveryStageRecordV2(
                item_id=item_id,
                request_hash=self.request_hash,
                input_hash=identity,
                role=role,
                ai_run_id=run_id,
                output_json=value.model_dump(mode="json"),
            ),
            "comparison_discovery_stage",
        )
        return value, run_id, identity

    @staticmethod
    def fact_constraints(source: GroundedSource) -> list[dict[str, Any]]:
        return [
            {
                "fact_id": str(f.fact_id),
                "literal_qualifiers": [
                    v for v in (f.conditions, f.region, f.attribution, f.unit, f.currency) if v
                ],
                "requires_conditional_status": bool(f.conditions),
            }
            for f in source.evidence.verified_facts
        ]

    def source_context_data(self, source: GroundedSource) -> dict[str, Any]:
        data = self.source_data(source)
        data["fact_constraints"] = self.fact_constraints(source)
        data["published_at"] = (
            source.evidence.published_at.isoformat() if source.evidence.published_at else None
        )
        data["temporal_scope"] = "announcement_time_disclosure; current_availability_unconfirmed"
        data["source_context"] = [
            {**v.model_dump(mode="json"), "text": redact_contacts(v.text), "contacts_masked": True}
            for v in coalesced_contexts(source)
        ]
        return data

    def discover(
        self,
        request: ComparisonDiscoveryRequestV2,
        baseline: SourceExclusionBaselineV1 | None = None,
    ) -> ComparisonDiscoveryAuditV2:
        self.request = request
        models = [
            self.runner.profile(role).model
            for role in (
                "discovery_plan",
                "discovery_assess",
                "discovery_review",
            )
        ]
        if not all(models) or models[2] in models[:2]:
            raise EditorialError("DISCOVERY_INDEPENDENT_MODEL_REQUIRED")
        rejected: dict[str, str] = {}
        sources: dict[UUID, GroundedSource] = {}
        ids = request.candidate_item_ids
        if not ids:
            ids = tuple(
                self.session.scalars(
                    select(Item.id)
                    .where(
                        Item.duplicate_of_id.is_(None),
                    )
                    .order_by(Item.published_at.desc(), Item.id)
                    .limit(self.settings.research_max_candidates)
                )
            )
        for key in dict.fromkeys((request.seed_item_id, *ids)):
            try:
                source = self.source(key)
                primary_product(source)
                if excluded(source, baseline):
                    raise EditorialError("DISCOVERY_PREVIOUSLY_USED_SOURCE")
                sources[key] = source
            except EditorialError as exc:
                rejected[str(key)] = exc.code
        if request.seed_item_id not in sources:
            raise EditorialError("DISCOVERY_SEED_NOT_ELIGIBLE")
        texts = {
            key: " ".join(f.value for f in s.evidence.verified_facts) for key, s in sources.items()
        }
        ranked, scores = rank_candidates(request.seed_item_id, texts, request.editorial_intent)
        distinct: list[UUID] = []
        product_keys: set[str] = set()
        body_hashes: set[str] = set()
        for key in ranked:
            product = primary_product(sources[key])
            if (
                product.product_key in product_keys
                or sources[key].document.body_hash in body_hashes
            ):
                rejected[str(key)] = "DISCOVERY_DUPLICATE_PRODUCT_OR_CONTENT"
                continue
            distinct.append(key)
            product_keys.add(product.product_key)
            body_hashes.add(sources[key].document.body_hash)
        pool = distinct[: request.retrieval_pool_size]
        detailed = pool[: request.detailed_pool_size]
        retrieval = RetrievalCandidateSetV2(
            method="keyword",
            ranked_item_ids=tuple(pool),
            detailed_item_ids=tuple(detailed),
            rejected=rejected,
            ranking={str(k): scores[k] for k in ranked},
        )
        profiles = tuple(
            ProductComparisonProfileV2(
                product=primary_product(sources[k]),
                search_text=texts[k],
                fact_ids=tuple(sources[k].anchors),
            )
            for k in pool
        )
        self.request_hash = canonical_payload_hash(
            {
                "request": request.model_dump(
                    mode="json", exclude=({"budget_id"} if request.budget_id is None else set())
                ),
                "retrieval": retrieval.model_dump(mode="json"),
                "documents": [sources[k].document.model_dump(mode="json") for k in pool],
                "baseline": baseline.model_dump(mode="json") if baseline else None,
                "profiles": [
                    self.runner.profile(role).fingerprint
                    for role in (
                        "discovery_plan",
                        "discovery_assess",
                        "discovery_review",
                    )
                    + (("discovery_groups",) if request.group_selection == "semantic" else ())
                    + (("discovery_profiles",) if request.semantic_profiles else ())
                    + (("discovery_inventory",) if request.evidence_first else ())
                ],
                "policy": POLICY_VERSION,
                "group_ranking_policy": (
                    "semantic_group_proposal-v1"
                    if request.group_selection == "semantic"
                    else "keyword_group_mmr-v1-0.7"
                ),
            }
        )
        seed = request.seed_item_id
        group_ranking = tuple(
            DiscoveryGroupRankingV2(
                item_ids=value.item_ids,
                relatedness=value.relatedness,
                redundancy=value.redundancy,
                selection_score=value.selection_score,
                selected=index < request.maximum_groups,
            )
            for index, value in enumerate(
                value
                for value in rank_seeded_groups(seed, detailed, texts)
                if not any(set(value.item_ids) == set(g) for g in request.excluded_group_item_ids)
            )
        )
        groups: list[ComparisonGroupEvaluationV2] = []
        planning: list[DiscoveryGroupPlanningV2] = []
        reasons: list[str] = []
        semantic_selection = None
        semantic_run = None
        semantic_profiles_run = None
        if request.group_selection == "semantic":
            catalog = []
            for key in pool:
                source = sources[key]
                data = self.source_context_data(source)
                catalog.append(
                    {
                        "item_id": str(key),
                        "product_name": primary_product(source).name,
                        "published_at": data["published_at"],
                        "temporal_scope": data["temporal_scope"],
                        "facts": data["facts"],
                    }
                )
            group_ranking = ()
            detailed = []
            try:
                if request.semantic_profiles:
                    batch, semantic_profiles_run, _ = self.discovery_stage(
                        "discovery_profiles",
                        seed,
                        {"catalog": catalog},
                        DiscoverySemanticProfilesV2,
                        partial(validate_semantic_profiles, sources={k: sources[k] for k in pool}),
                    )
                    by_item = {p.item_id: p for p in batch.profiles}
                    profiles = tuple(
                        p.model_copy(
                            update={
                                "semantic": by_item[k],
                                "representation": "grounded_semantic_and_keywords",
                            }
                        )
                        for k, p in zip(pool, profiles, strict=True)
                    )
                    for entry in catalog:
                        entry["semantic_profile"] = by_item[UUID(entry["item_id"])].model_dump(
                            mode="json"
                        )
                semantic_selection, semantic_run, _ = self.discovery_stage(
                    "discovery_groups",
                    seed,
                    {
                        "catalog": catalog,
                        "seed_item_id": str(seed),
                        "editorial_intent": request.editorial_intent,
                        "maximum_groups": request.maximum_groups,
                        "detailed_pool_size": request.detailed_pool_size,
                        "excluded_group_item_ids": [
                            [str(k) for k in g] for g in request.excluded_group_item_ids
                        ],
                        "output_contract_hash": canonical_payload_hash(
                            DiscoveryGroupSelectionV2.model_json_schema()
                        ),
                    },
                    DiscoveryGroupSelectionV2,
                    partial(
                        validate_group_selection,
                        sources={key: sources[key] for key in pool},
                        request=request,
                    ),
                )
                group_ranking = tuple(
                    DiscoveryGroupRankingV2(
                        item_ids=(g.item_ids[0], g.item_ids[1], g.item_ids[2]),
                        relatedness=0,
                        redundancy=0,
                        selection_score=0,
                        selected=True,
                        method="semantic_group_proposal",
                    )
                    for g in semantic_selection.groups
                )
                detailed = list(dict.fromkeys(k for g in group_ranking for k in g.item_ids))
                if not group_ranking:
                    reasons.append("DISCOVERY_NO_USEFUL_HYPOTHESIS")
            except EditorialError as exc:
                if exc.code in {"PAYLOAD_HASH_MISMATCH", "DISCOVERY_STAGE_RECORD_INVALID"}:
                    raise
                reasons.append(exc.code)
            retrieval = retrieval.model_copy(update={"detailed_item_ids": tuple(detailed)})
        for ranked_group in group_ranking[: request.maximum_groups]:
            selected_sources = {k: sources[k] for k in ranked_group.item_ids}
            data = {
                "sources": [self.source_context_data(s) for s in selected_sources.values()],
                "editorial_intent": request.editorial_intent,
                "maximum_hypotheses": request.maximum_hypotheses_per_group,
            }
            if semantic_selection is not None:
                hint = next(
                    g for g in semantic_selection.groups if g.item_ids == ranked_group.item_ids
                )
                data["tentative_group_hint"] = hint.model_dump(mode="json")
            inventory = None
            inventory_run = None
            try:
                if request.evidence_first:
                    inventory, inventory_run, _ = self.discovery_stage(
                        "discovery_inventory",
                        seed,
                        data,
                        DiscoveryEvidenceInventoryV2,
                        partial(validate_evidence_inventory, sources=selected_sources),
                    )
                    data["tentative_evidence_inventory"] = inventory.model_dump(mode="json")

                def validate_proposal(
                    value: ComparisonGroupProposalV2,
                    own_sources: dict[UUID, GroundedSource] = selected_sources,
                ) -> None:
                    if len(value.hypotheses) > request.maximum_hypotheses_per_group:
                        raise EditorialError("DISCOVERY_HYPOTHESIS_BUDGET_EXCEEDED")
                    for index, hypothesis in enumerate(value.hypotheses):
                        try:
                            validate_hypothesis(hypothesis, own_sources, require_support=True)
                        except EditorialError as exc:
                            raise EditorialError(
                                exc.code, path=("hypotheses", index, *exc.path)
                            ) from exc

                proposal, plan_run, plan_hash = self.discovery_stage(
                    "discovery_plan",
                    seed,
                    data,
                    ComparisonGroupProposalV2,
                    validate_proposal,
                )
                planning.append(
                    DiscoveryGroupPlanningV2(
                        item_ids=ranked_group.item_ids,
                        ai_run_id=plan_run,
                        proposal=proposal,
                        evidence_inventory=inventory,
                        evidence_inventory_ai_run_id=inventory_run,
                    )
                )
                if not proposal.hypotheses:
                    reasons.append("DISCOVERY_NO_USEFUL_HYPOTHESIS")
                for index, hypothesis in enumerate(proposal.hypotheses):
                    frozen_plan = ComparisonHypothesisV2(
                        hypothesis_id=uuid5(NAMESPACE_URL, plan_hash + ":" + str(index)),
                        input_hash=plan_hash,
                        ai_run_id=plan_run,
                        hypothesis=hypothesis,
                        products=tuple(primary_product(s) for s in selected_sources.values()),
                    )
                    group = self.evaluate_hypothesis(
                        frozen_plan,
                        selected_sources,
                        data,
                        proposal.unsuitable_reasons,
                    )
                    groups.append(group)
                    self.record(group, "comparison_discovery_group")
                    for code in group.issues:
                        if (
                            code.startswith("DISCOVERY_AI_")
                            or code == "DISCOVERY_API_BUDGET_EXHAUSTED"
                        ):
                            reasons.append(code)
                    if "DISCOVERY_API_BUDGET_EXHAUSTED" in group.issues:
                        break
            except EditorialError as exc:
                if exc.code in {"PAYLOAD_HASH_MISMATCH", "DISCOVERY_STAGE_RECORD_INVALID"}:
                    raise
                planning.append(
                    DiscoveryGroupPlanningV2(
                        item_ids=ranked_group.item_ids,
                        error_code=exc.code,
                        evidence_inventory=inventory,
                        evidence_inventory_ai_run_id=inventory_run,
                    )
                )
                reasons.append(exc.code)
                if exc.code in {"DISCOVERY_API_BUDGET_EXHAUSTED", "AI_NOT_CONFIGURED"}:
                    break
        accepted_groups = [g for g in groups if g.accepted]
        selected = (
            max(accepted_groups, key=lambda g: sum(e.evaluation.score for e in g.evaluations))
            if accepted_groups
            else None
        )
        if len(detailed) < 3:
            reasons.append("DISCOVERY_INSUFFICIENT_DISTINCT_PRODUCTS")
        if selected is None:
            reasons.append("DISCOVERY_NO_ACCEPTED_HYPOTHESIS")
        audit = ComparisonDiscoveryAuditV2(
            item_id=seed,
            input_hash=self.request_hash,
            evaluated_at=datetime.now(UTC),
            request=request,
            retrieval=retrieval,
            profiles=profiles,
            group_ranking=group_ranking,
            planning=tuple(planning),
            semantic_group_selection=semantic_selection,
            semantic_group_selection_ai_run_id=semantic_run,
            semantic_profiles_ai_run_id=semantic_profiles_run,
            scope=(
                "registered_sources; "
                + request.group_selection
                + "_joint_discovery; no_external_search; no_delivery"
            ),
            contexts=tuple(v for k in detailed for v in contexts(sources[k])),
            groups=tuple(groups),
            outcome="eligible" if selected else "deferred",
            selected_hypothesis_id=selected.plan.hypothesis_id if selected else None,
            frozen_hash=canonical_payload_hash(selected.model_dump(mode="json"))
            if selected
            else None,
            api_calls_used=self.used_calls(),
            reason_codes=tuple(dict.fromkeys(reasons)),
        )
        self.record(audit, "comparison_discovery_audit")
        return audit

    def validate_frozen(
        self,
        audit: ComparisonDiscoveryAuditV2,
    ) -> ComparisonGroupEvaluationV2:
        """Re-read current source versions and actual AI records without new AI calls."""
        group = frozen_group(audit)
        sources = {}
        for product in group.plan.products:
            for document in product.documents:
                source = self.source(document.item_id)
                if source.document != document or primary_product(source) != product:
                    raise EditorialError("DISCOVERY_FROZEN_SOURCE_CHANGED")
                sources[document.item_id] = source
        validate_hypothesis(group.plan.hypothesis, sources, require_support=True)
        assert group.independent is not None
        validate_review(group.independent, sources)
        plan_run = self.session.get(AiRun, group.plan.ai_run_id)
        review_run = self.session.get(AiRun, group.independent_ai_run_id)
        if (
            review_run is not None
            and review_run.prompt_version != self.runner.profile("discovery_review").prompt_version
        ):
            raise EditorialError("DISCOVERY_FROZEN_REVIEW_POLICY_CHANGED")
        if (
            plan_run is None
            or review_run is None
            or plan_run.execution_role != "discovery_plan"
            or review_run.execution_role != "discovery_review"
            or plan_run.item_id != audit.item_id
            or review_run.item_id != audit.item_id
            or plan_run.validation_status != "valid"
            or review_run.validation_status != "valid"
            or review_run.output_json != group.independent.model_dump(mode="json")
            or group.plan.hypothesis.model_dump(mode="json")
            not in ((plan_run.output_json or {}).get("hypotheses", []))
        ):
            raise EditorialError("DISCOVERY_FROZEN_AI_RECORD_INVALID")
        models = {plan_run.model}
        for entry in group.evaluations:
            expected = entry.evaluation.model_dump(mode="json")
            expected["reason"] = {
                "text": entry.evaluation.reason.text,
                "fact_ids": [str(a.fact_id) for a in entry.evaluation.reason.evidence],
            }
            for cell, raw in zip(entry.evaluation.cells, expected["cells"], strict=True):
                raw.pop("evidence")
                raw["fact_ids"] = [str(a.fact_id) for a in cell.evidence]
            source = sources[entry.product.documents[0].item_id]
            referenced = CandidateSuitabilityAIOutputV1.model_validate(expected)
            self.validate_assessment(referenced, group.plan.hypothesis.questions, source)
            if bind_candidate(referenced, source) != entry.evaluation:
                raise EditorialError("DISCOVERY_FROZEN_GROUNDING_CHANGED")
            run = self.session.get(AiRun, entry.ai_run_id)
            if (
                run is None
                or run.execution_role != "discovery_assess"
                or run.item_id != source.document.item_id
                or run.validation_status != "valid"
                or run.output_json != expected
            ):
                raise EditorialError("DISCOVERY_FROZEN_AI_RECORD_INVALID")
            models.add(run.model)
        if review_run.model in models:
            raise EditorialError("DISCOVERY_INDEPENDENT_MODEL_REQUIRED")
        return group

    def evaluate_hypothesis(
        self,
        frozen_plan: ComparisonHypothesisV2,
        sources: dict[UUID, GroundedSource],
        data: dict[str, Any],
        unsuitable_reasons: tuple[str, ...],
    ) -> ComparisonGroupEvaluationV2:
        hypothesis = frozen_plan.hypothesis
        seed = self.request.seed_item_id
        evaluations: list[DiscoveryProductEvaluationV2] = []
        self.record(frozen_plan, "comparison_discovery_hypothesis")
        try:
            for key, source in sources.items():
                assessment_data = {
                    "source": self.source_context_data(source),
                    "candidate_product_name": primary_product(source).name,
                    "selection_task": hypothesis.selection_question,
                    "plan": {"plan": hypothesis.model_dump(mode="json")},
                    "fact_constraints": self.fact_constraints(source),
                }
                result, run_id, _ = self.discovery_stage(
                    "discovery_assess",
                    key,
                    assessment_data,
                    CandidateSuitabilityAIOutputV1,
                    partial(
                        self.validate_assessment,
                        questions=hypothesis.questions,
                        source=source,
                    ),
                )
                evaluations.append(
                    DiscoveryProductEvaluationV2(
                        product=primary_product(source),
                        ai_run_id=run_id,
                        evaluation=bind_candidate(result, source),
                    )
                )
            group = ComparisonGroupEvaluationV2(
                plan=frozen_plan,
                evaluations=tuple(evaluations),
                issues=unsuitable_reasons,
            )
            issues = (*unsuitable_reasons, *group_issues(group))
            group = group.model_copy(update={"issues": tuple(dict.fromkeys(issues))})
            if not group.issues:
                review, review_id, _ = self.discovery_stage(
                    "discovery_review",
                    seed,
                    {
                        "sources": data["sources"],
                        "editorial_intent": data["editorial_intent"],
                        "group": group.model_dump(mode="json"),
                    },
                    DiscoveryReviewV2,
                    partial(validate_review, sources=sources),
                )
                accepted = (
                    all(c.result == "pass" for c in review.checks) and not review.blocking_issues
                )
                group = group.model_copy(
                    update={
                        "independent": review,
                        "independent_ai_run_id": review_id,
                        "accepted": accepted,
                    }
                )
        except EditorialError as exc:
            if exc.code in {"PAYLOAD_HASH_MISMATCH", "DISCOVERY_STAGE_RECORD_INVALID"}:
                raise
            return ComparisonGroupEvaluationV2(
                plan=frozen_plan,
                evaluations=tuple(evaluations),
                issues=(*unsuitable_reasons, exc.code),
            )
        return group

    validate_assessment = staticmethod(validate_product_assessment)
