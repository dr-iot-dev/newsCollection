"""Model outputs select fact IDs; trusted source records supply quotation offsets."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.contracts.base import ContractModel
from app.contracts.comparison_selection_v1 import ComparisonQuestionV1


class GroundedJudgmentRefV1(ContractModel):
    text: str = Field(min_length=1, max_length=1000)
    fact_ids: tuple[UUID, ...] = Field(min_length=1)


class ComparisonPlanAIOutputV1(ContractModel):
    product: GroundedJudgmentRefV1
    product_kind: GroundedJudgmentRefV1
    role: GroundedJudgmentRefV1
    audience: GroundedJudgmentRefV1
    environment: GroundedJudgmentRefV1
    purpose: GroundedJudgmentRefV1
    selection_question: str = Field(min_length=1, max_length=1000)
    eligible_roles: tuple[str, ...] = Field(min_length=1)
    excluded_roles: tuple[str, ...]
    questions: tuple[ComparisonQuestionV1, ...] = Field(min_length=3, max_length=10)
    search_queries: tuple[str, ...] = Field(min_length=1, max_length=8)
    context_status: Literal["ready", "needs_information"] = "needs_information"
    missing_information: tuple[str, ...]


class ComparisonCellRefV1(ContractModel):
    question_key: str
    status: Literal[
        "documented", "unsupported", "conditional", "planned", "unknown", "incomparable"
    ]
    answer: str = Field(min_length=1, max_length=1000)
    fact_ids: tuple[UUID, ...]
    conditions: tuple[str, ...]
    plan: str | None
    version: str | None
    region: str | None
    as_of: str | None


class CandidateSuitabilityAIOutputV1(ContractModel):
    decision: Literal["eligible", "needs_information", "rejected"]
    role_fit: Literal["pass", "fail", "unknown"]
    purpose_fit: Literal["pass", "fail", "unknown"]
    audience_fit: Literal["pass", "fail", "unknown"]
    reason: GroundedJudgmentRefV1
    score: int = Field(ge=0, le=100)
    cells: tuple[ComparisonCellRefV1, ...]
    missing_question_keys: tuple[str, ...]
    uncertainties: tuple[str, ...]
