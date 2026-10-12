"""Versioned, grounded contracts for semantic comparison selection.

Editorial judgments are separate from product facts. Evidence anchors always
refer to a verified fact and an exact passage of its own source document.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from nw_ground._vendor.contracts.base import ContractModel

POLICY_VERSION = "comparison-selection-v1"


class GroundingV1(ContractModel):
    item_id: UUID
    fact_id: UUID
    evidence_id: UUID
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=1000)


class GroundedJudgmentV1(ContractModel):
    text: str = Field(min_length=1, max_length=1000)
    evidence: tuple[GroundingV1, ...] = Field(min_length=1)


class ComparisonQuestionV1(ContractModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=500)
    required: bool
    answer_format: str = Field(min_length=1, max_length=300)
    applicability: str = Field(min_length=1, max_length=500)
    evidence_requirement: str = Field(min_length=1, max_length=500)


class ComparisonPlanOutputV1(ContractModel):
    product: GroundedJudgmentV1
    product_kind: GroundedJudgmentV1
    role: GroundedJudgmentV1
    audience: GroundedJudgmentV1
    environment: GroundedJudgmentV1
    purpose: GroundedJudgmentV1
    selection_question: str = Field(min_length=1, max_length=1000)
    eligible_roles: tuple[str, ...] = Field(min_length=1)
    excluded_roles: tuple[str, ...]
    questions: tuple[ComparisonQuestionV1, ...] = Field(min_length=3, max_length=10)
    search_queries: tuple[str, ...] = Field(min_length=1, max_length=8)
    context_status: Literal["ready", "needs_information"] = "needs_information"
    missing_information: tuple[str, ...]

    @model_validator(mode="after")
    def unique_questions(self) -> "ComparisonPlanOutputV1":
        if len({q.key for q in self.questions}) != len(self.questions):
            raise ValueError("Comparison question keys must be unique")
        if not 3 <= sum(q.required for q in self.questions) <= 5:
            raise ValueError("A plan requires three to five mandatory questions")
        return self


class ComparisonPlanV1(ContractModel):
    plan_id: UUID
    item_id: UUID
    item_version: int = Field(ge=1)
    revision: int = Field(ge=1)
    policy_version: str = POLICY_VERSION
    input_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    extraction_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    evidence_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    ai_run_id: UUID
    plan: ComparisonPlanOutputV1
    editorial_intent: str | None = Field(default=None, min_length=1, max_length=2000)


class ProductDocumentV1(ContractModel):
    item_id: UUID
    item_version: int = Field(ge=1)
    url: str
    extraction_hash: str
    evidence_hash: str
    body_hash: str
    announcement_key: str
    role: Literal["announcement", "features", "pricing", "specification"]


class ComparedProductV1(ContractModel):
    product_key: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=300)
    identity: GroundingV1
    documents: tuple[ProductDocumentV1, ...] = Field(min_length=1)


class ComparisonCellV1(ContractModel):
    question_key: str
    status: Literal[
        "documented", "unsupported", "conditional", "planned", "unknown", "incomparable"
    ]
    answer: str = Field(min_length=1, max_length=1000)
    evidence: tuple[GroundingV1, ...]
    conditions: tuple[str, ...]
    plan: str | None
    version: str | None
    region: str | None
    as_of: str | None


class CandidateSuitabilityV1(ContractModel):
    decision: Literal["eligible", "needs_information", "rejected"]
    role_fit: Literal["pass", "fail", "unknown"]
    purpose_fit: Literal["pass", "fail", "unknown"]
    audience_fit: Literal["pass", "fail", "unknown"]
    reason: GroundedJudgmentV1
    score: int = Field(ge=0, le=100)
    cells: tuple[ComparisonCellV1, ...]
    missing_question_keys: tuple[str, ...]
    uncertainties: tuple[str, ...]


class CandidateEvaluationV1(ContractModel):
    plan_id: UUID
    policy_version: str = POLICY_VERSION
    input_hash: str
    product: ComparedProductV1
    ai_run_id: UUID
    evaluation: CandidateSuitabilityV1


INDEPENDENT_CHECKS = (
    "same_selection_task",
    "same_question_per_row",
    "required_and_majority_coverage",
    "evidence_and_conditions",
    "specific_adoption_reasons",
)


class ComparisonSuitabilityCheckV1(ContractModel):
    key: Literal[
        "same_selection_task",
        "same_question_per_row",
        "required_and_majority_coverage",
        "evidence_and_conditions",
        "specific_adoption_reasons",
    ]
    result: Literal["pass", "fail", "unknown"]
    reason: str = Field(min_length=1, max_length=1000)
    fact_ids: tuple[UUID, ...]


class ComparisonSuitabilityOutputV1(ContractModel):
    checks: tuple[ComparisonSuitabilityCheckV1, ...] = Field(min_length=5, max_length=5)
    blocking_issues: tuple[str, ...]

    @model_validator(mode="after")
    def complete_checks(self) -> "ComparisonSuitabilityOutputV1":
        if {c.key for c in self.checks} != set(INDEPENDENT_CHECKS):
            raise ValueError("All independent checks must appear exactly once")
        return self


class SourceExclusionEntryV1(ContractModel):
    url: str
    body_hash: str | None = None
    announcement_key: str | None = None
    source: Literal["wordpress", "local_history", "batch"]


class SourceExclusionBaselineV1(ContractModel):
    baseline_id: UUID
    batch_id: UUID | None = None
    policy_version: str = POLICY_VERSION
    captured_at: datetime
    scope: Literal["batch", "global"]
    entries: tuple[SourceExclusionEntryV1, ...]


class ComparisonStageRecordV1(ContractModel):
    item_id: UUID
    policy_version: str = POLICY_VERSION
    input_hash: str
    stage: Literal["plan", "candidate", "independent"]
    ai_run_id: UUID
    output_json: dict[str, Any]


class ComparisonSelectionAuditV1(ContractModel):
    item_id: UUID
    policy_version: str = POLICY_VERSION
    input_hash: str
    mode: Literal["shadow"] = "shadow"
    scope: str = "registered_sources_only; external_search_not_configured"
    plan: ComparisonPlanV1
    exclusion_baseline: SourceExclusionBaselineV1 | None = None
    evaluations: tuple[CandidateEvaluationV1, ...]
    selected_product_keys: tuple[str, ...]
    independent_ai_run_id: UUID | None = None
    independent: ComparisonSuitabilityOutputV1 | None = None
    outcome: Literal["eligible", "deferred"]
    reason_codes: tuple[str, ...]
    missing_question_keys: tuple[str, ...]
    minimum_products: int = Field(ge=2)
    minimum_sources: int = Field(ge=1)
