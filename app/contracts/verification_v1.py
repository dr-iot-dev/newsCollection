from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.contracts.base import ContractModel


class CriterionResult(StrEnum):
    PASSED = "pass"
    FAIL = "fail"
    WARN = "warn"


class VerificationCriterionV1(ContractModel):
    key: str
    result: CriterionResult
    detail: str
    fact_ids: tuple[UUID, ...] = ()


class VerificationReportV1(ContractModel):
    overall_result: Literal["pass", "fail", "error"] = "fail"
    draft_revision: int = 1
    draft_hash: str = ""
    article_package_hash: str = ""
    verification_id: UUID
    draft_id: UUID
    article_package_id: UUID
    policy_version: str
    verifier_profile_key: str
    criteria: tuple[VerificationCriterionV1, ...]
    blocking_issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
