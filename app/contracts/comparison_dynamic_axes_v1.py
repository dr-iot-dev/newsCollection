"""Group-level axis discovery, extraction and selection audit contracts."""

from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import Field

from app.contracts.base import ContractModel
from app.contracts.comparison_pair_discovery_v3 import PairDocument, PairProduct, SourceQuote

POLICY = "comparison-dynamic-axes-v1"
SEARCH_POLICY = "comparison-axis-literal-search-v1"
AxisSearchTerm = Annotated[str, Field(min_length=2, max_length=24)]


class DynamicAxis(ContractModel):
    axis_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=500)
    layer: Literal["input", "mechanism", "output", "operations"]
    evidence: tuple[SourceQuote, ...] = Field(min_length=1)
    # Empty default permits reading historical audits; new discovery validates nonempty terms.
    search_terms: tuple[AxisSearchTerm, ...] = ()


class AxisCandidates(ContractModel):
    axes: tuple[DynamicAxis, ...]


class AxisCell(ContractModel):
    axis_id: str
    status: Literal[
        "supported", "not_supported", "conditional", "planned", "unknown", "incomparable"
    ]
    answer: str
    conditions: str
    evidence: tuple[SourceQuote, ...]


class AxisValues(ContractModel):
    product: PairProduct
    cells: tuple[AxisCell, ...]


class AxisAssessment(ContractModel):
    axis_id: str
    answers_fit_question: bool
    useful: bool
    distinct: bool
    reason: str = Field(min_length=1)


class AxisSelection(ContractModel):
    purpose: str
    same_selection_task: bool
    selected_axis_ids: tuple[str, ...] = Field(max_length=6)
    assessments: tuple[AxisAssessment, ...]
    reason: str


class AxisReviewCheck(ContractModel):
    axis_id: str
    answers_fit_question: bool
    evidence_valid: bool
    conditions_preserved: bool
    useful: bool
    distinct: bool
    reason: str


class AxisReview(ContractModel):
    same_selection_task: bool
    checks: tuple[AxisReviewCheck, ...]
    reason: str


class DynamicAxesRequest(ContractModel):
    run_id: UUID = Field(default_factory=uuid4)
    documents: tuple[PairDocument, ...] = Field(min_length=3, max_length=5)
    editorial_intent: str = ""
    minimum_axes: int = Field(default=3, ge=1, le=6)
    mode: Literal["shadow", "discovery_only"] = "shadow"


class DynamicAxesState(ContractModel):
    request: DynamicAxesRequest
    fingerprint: str
    policy: str = POLICY
    status: Literal[
        "running", "paused_budget", "waiting_retry", "held", "selection_passed", "candidates_ready"
    ] = "running"
    reason: str = ""
    candidates: AxisCandidates | None = None
    values: tuple[AxisValues, ...] = ()
    coverage: dict[str, int] = Field(default_factory=dict)
    selection: AxisSelection | None = None
    review: AxisReview | None = None
    initial_review: AxisReview | None = None
    repair_round: int = Field(default=0, ge=0, le=1)
    stages: dict[str, Any] = Field(default_factory=dict)
    ai_calls: int = 0
    ai_run_ids: tuple[UUID, ...] = ()


class PassageRef(ContractModel):
    item_id: UUID
    passage_id: str


class AxisCandidateRef(ContractModel):
    axis_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=2, max_length=24)
    question: str = Field(min_length=1, max_length=500)
    layer: Literal["input", "mechanism", "output", "operations"]
    evidence: tuple[PassageRef, ...] = Field(min_length=1)
    search_terms: tuple[AxisSearchTerm, ...] = Field(min_length=1)


class AxisCandidatesRef(ContractModel):
    axes: tuple[AxisCandidateRef, ...]


class AxisProductRef(ContractModel):
    item_id: UUID
    name: str
    organization: str
    evidence: tuple[PassageRef, ...] = Field(min_length=1)


class AxisCellRef(ContractModel):
    axis_id: str
    status: Literal[
        "supported", "not_supported", "conditional", "planned", "unknown", "incomparable"
    ]
    answer: str
    conditions: str
    evidence: tuple[PassageRef, ...]


class AxisValuesRef(ContractModel):
    product: AxisProductRef
    cells: tuple[AxisCellRef, ...]
