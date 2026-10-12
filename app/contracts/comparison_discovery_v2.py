"""Joint discovery contracts. These audits never masquerade as V1 selection approval."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.base import ContractModel
from app.contracts.comparison_selection_ai_v1 import ComparisonCellRefV1, GroundedJudgmentRefV1
from app.contracts.comparison_selection_v1 import (
    CandidateSuitabilityV1,
    ComparedProductV1,
    ComparisonQuestionV1,
)

POLICY_VERSION: Literal["comparison-discovery-v2"] = "comparison-discovery-v2"
CHECKS = (
    "same_selection_task",
    "same_question_per_row",
    "required_and_majority_coverage",
    "evidence_and_conditions",
    "specific_adoption_reasons",
    "material_omissions",
)


class ComparisonDiscoveryRequestV2(ContractModel):
    seed_item_id: UUID
    budget_id: UUID | None = None
    group_selection: Literal["keyword_mmr", "semantic"] = "keyword_mmr"
    semantic_profiles: bool = False
    evidence_first: bool = False
    excluded_group_item_ids: tuple[tuple[UUID, ...], ...] = Field(default=(), max_length=20)
    candidate_item_ids: tuple[UUID, ...] = ()
    editorial_intent: str | None = Field(default=None, min_length=1, max_length=2000)
    maximum_groups: int = Field(default=3, ge=1, le=5)
    maximum_hypotheses_per_group: int = Field(default=2, ge=1, le=2)
    maximum_api_calls: int = Field(default=30, ge=1, le=30)
    detailed_pool_size: int = Field(default=10, ge=3, le=10)
    retrieval_pool_size: int = Field(default=30, ge=3, le=100)

    @model_validator(mode="after")
    def discovery_modes(self) -> "ComparisonDiscoveryRequestV2":
        if self.semantic_profiles and self.group_selection != "semantic":
            raise ValueError("Semantic profiles require semantic grouping")
        sets = [frozenset(group) for group in self.excluded_group_item_ids]
        if any(
            len(group) != 3 or len(set(group)) != 3 or self.seed_item_id not in group
            for group in self.excluded_group_item_ids
        ) or len(set(sets)) != len(sets):
            raise ValueError("Excluded groups must be distinct seeded triples")
        return self


class DiscoverySemanticProfileV2(ContractModel):
    item_id: UUID
    role: GroundedJudgmentRefV1 | None
    purpose: GroundedJudgmentRefV1 | None
    targets: GroundedJudgmentRefV1 | None
    method: GroundedJudgmentRefV1 | None
    results: GroundedJudgmentRefV1 | None
    material_missing_information: tuple[str, ...] = Field(max_length=8)


class DiscoverySemanticProfilesV2(ContractModel):
    profiles: tuple[DiscoverySemanticProfileV2, ...] = Field(min_length=3, max_length=100)


class ProductComparisonProfileV2(ContractModel):
    product: ComparedProductV1
    search_text: str
    fact_ids: tuple[UUID, ...]
    semantic: DiscoverySemanticProfileV2 | None = None
    representation: Literal["verified_facts_keywords", "grounded_semantic_and_keywords"] = (
        "verified_facts_keywords"
    )


class RetrievalCandidateSetV2(ContractModel):
    method: Literal["keyword", "hybrid"]
    ranked_item_ids: tuple[UUID, ...]
    detailed_item_ids: tuple[UUID, ...]
    rejected: dict[str, str]
    ranking: dict[str, float]


class DiscoveryGroupRankingV2(ContractModel):
    item_ids: tuple[UUID, UUID, UUID]
    relatedness: float = Field(ge=0, le=1)
    redundancy: float = Field(ge=0, le=1)
    selection_score: float = Field(ge=-1, le=1)
    selected: bool
    method: Literal["keyword_group_mmr", "semantic_group_proposal"] = "keyword_group_mmr"


class FactContextBindingV2(ContractModel):
    item_id: UUID
    fact_id: UUID
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    # This is source context, not a newly extracted or verified product fact.
    representation: Literal["source_context_only"] = "source_context_only"


class SourceContextSpanV2(ContractModel):
    item_id: UUID
    fact_ids: tuple[UUID, ...] = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    representation: Literal["source_context_only"] = "source_context_only"


class DiscoveryProductReasonV2(ContractModel):
    item_id: UUID
    judgment: GroundedJudgmentRefV1


class DiscoveryGroupHintV2(ContractModel):
    item_ids: tuple[UUID, ...] = Field(min_length=3, max_length=3)
    selection_task: GroundedJudgmentRefV1
    product_reasons: tuple[DiscoveryProductReasonV2, ...] = Field(min_length=3, max_length=3)


class DiscoveryGroupSelectionV2(ContractModel):
    groups: tuple[DiscoveryGroupHintV2, ...] = Field(max_length=5)
    unsuitable_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def explained_abstention(self) -> "DiscoveryGroupSelectionV2":
        if not self.groups and not self.unsuitable_reasons:
            raise ValueError("An empty group selection must explain the insufficiency")
        return self


class DiscoveryQuestionSupportV2(ContractModel):
    item_id: UUID
    cell: ComparisonCellRefV1


class DiscoveryEvidenceDimensionV2(ContractModel):
    question: ComparisonQuestionV1
    supports: tuple[DiscoveryQuestionSupportV2, ...] = Field(min_length=3, max_length=3)


class DiscoveryEvidenceInventoryV2(ContractModel):
    dimensions: tuple[DiscoveryEvidenceDimensionV2, ...] = Field(max_length=6)
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def distinct_dimensions(self) -> "DiscoveryEvidenceInventoryV2":
        if len({d.question.key for d in self.dimensions}) != len(self.dimensions):
            raise ValueError("Inventory questions must be distinct")
        if not self.dimensions and not self.limitations:
            raise ValueError("An empty inventory must explain the gaps")
        return self


class ComparisonHypothesisOutputV2(ContractModel):
    purpose: GroundedJudgmentRefV1
    audience: GroundedJudgmentRefV1
    selection_question: str = Field(min_length=1, max_length=1000)
    eligible_roles: tuple[str, ...] = Field(min_length=1)
    excluded_roles: tuple[str, ...]
    questions: tuple[ComparisonQuestionV1, ...] = Field(min_length=3, max_length=7)
    product_reasons: tuple[DiscoveryProductReasonV2, ...] = Field(min_length=3, max_length=3)
    meaningful_differences: tuple[str, ...] = Field(min_length=1)
    material_missing_information: tuple[str, ...]
    # Older audits remain readable. Newly generated plans must supply this mapping.
    question_support: tuple[DiscoveryQuestionSupportV2, ...] = Field(default=(), max_length=21)

    @model_validator(mode="after")
    def question_limits(self) -> "ComparisonHypothesisOutputV2":
        if len({q.key for q in self.questions}) != len(self.questions):
            raise ValueError("Question keys must be unique")
        if not 3 <= sum(q.required for q in self.questions) <= 5:
            raise ValueError("Three to five major questions are required")
        if sum(not q.required for q in self.questions) > 2:
            raise ValueError("At most two optional questions")
        if len({r.item_id for r in self.product_reasons}) != 3:
            raise ValueError("Each product requires its own editorial adoption reason")
        return self


class ComparisonGroupProposalV2(ContractModel):
    hypotheses: tuple[ComparisonHypothesisOutputV2, ...] = Field(max_length=2)
    unsuitable_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def explained_abstention(self) -> "ComparisonGroupProposalV2":
        if not self.hypotheses and not self.unsuitable_reasons:
            raise ValueError("An empty proposal must explain why no useful hypothesis is supported")
        return self


class DiscoveryGroupPlanningV2(ContractModel):
    item_ids: tuple[UUID, UUID, UUID]
    ai_run_id: UUID | None = None
    proposal: ComparisonGroupProposalV2 | None = None
    error_code: str | None = None
    evidence_inventory: DiscoveryEvidenceInventoryV2 | None = None
    evidence_inventory_ai_run_id: UUID | None = None


class DiscoveryCheckV2(ContractModel):
    key: Literal[
        "same_selection_task",
        "same_question_per_row",
        "required_and_majority_coverage",
        "evidence_and_conditions",
        "specific_adoption_reasons",
        "material_omissions",
    ]
    result: Literal["pass", "fail", "unknown"]
    reason: str = Field(min_length=1, max_length=1000)
    fact_ids: tuple[UUID, ...]


class DiscoveryReviewV2(ContractModel):
    checks: tuple[DiscoveryCheckV2, ...] = Field(min_length=6, max_length=6)
    blocking_issues: tuple[str, ...]

    @model_validator(mode="after")
    def complete(self) -> "DiscoveryReviewV2":
        if {c.key for c in self.checks} != set(CHECKS):
            raise ValueError("All six independent checks must appear exactly once")
        return self


class ComparisonHypothesisV2(ContractModel):
    hypothesis_id: UUID
    input_hash: str
    ai_run_id: UUID
    hypothesis: ComparisonHypothesisOutputV2
    products: tuple[ComparedProductV1, ...] = Field(min_length=3, max_length=3)


class DiscoveryProductEvaluationV2(ContractModel):
    product: ComparedProductV1
    ai_run_id: UUID
    evaluation: CandidateSuitabilityV1


class ComparisonGroupEvaluationV2(ContractModel):
    plan: ComparisonHypothesisV2
    evaluations: tuple[DiscoveryProductEvaluationV2, ...]
    issues: tuple[str, ...]
    independent: DiscoveryReviewV2 | None = None
    independent_ai_run_id: UUID | None = None
    accepted: bool = False


class DiscoveryStageRecordV2(ContractModel):
    item_id: UUID
    policy_version: Literal["comparison-discovery-v2"] = POLICY_VERSION
    request_hash: str
    input_hash: str
    role: str
    ai_run_id: UUID
    output_json: dict[str, Any]


class DiscoveryBudgetReservationV2(ContractModel):
    item_id: UUID
    request_hash: str
    budget_id: UUID | None = None
    ordinal: int = Field(ge=1)
    input_hash: str


class ComparisonDiscoveryAuditV2(ContractModel):
    item_id: UUID
    policy_version: Literal["comparison-discovery-v2"] = POLICY_VERSION
    input_hash: str
    evaluated_at: datetime
    mode: Literal["shadow"] = "shadow"
    request: ComparisonDiscoveryRequestV2
    retrieval: RetrievalCandidateSetV2
    profiles: tuple[ProductComparisonProfileV2, ...]
    group_ranking: tuple[DiscoveryGroupRankingV2, ...] = ()
    planning: tuple[DiscoveryGroupPlanningV2, ...] = ()
    semantic_group_selection: DiscoveryGroupSelectionV2 | None = None
    semantic_group_selection_ai_run_id: UUID | None = None
    semantic_profiles_ai_run_id: UUID | None = None
    contexts: tuple[FactContextBindingV2, ...]
    groups: tuple[ComparisonGroupEvaluationV2, ...]
    outcome: Literal["eligible", "deferred"]
    selected_hypothesis_id: UUID | None
    frozen_hash: str | None
    api_calls_used: int = Field(ge=0)
    reason_codes: tuple[str, ...]
    scope: str = "registered_sources; keyword_joint_discovery; no_external_search; no_delivery"
