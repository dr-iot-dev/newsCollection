from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.contracts.base import ContractModel


class CandidateOutcome(StrEnum):
    SELECTED = "selected"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class CandidateDecisionV1(ContractModel):
    item_id: UUID
    evidence_package_id: UUID
    decision: CandidateOutcome
    score: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...]
    missing_requirements: tuple[str, ...] = ()
    policy_version: str
