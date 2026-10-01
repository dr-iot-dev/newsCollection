from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool

from app.contracts.base import ContractModel

Category = Literal["generative_ai", "edge_ai", "iot_platform", "security", "standards"]


class SelectionOutputV1(ContractModel):
    decision: Literal["selected", "deferred", "rejected"]
    score: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    missing_requirements: tuple[str, ...] = ()


class DraftParagraphV1(ContractModel):
    text: str = Field(min_length=1, max_length=3000)
    fact_ids: tuple[UUID, ...] = Field(min_length=1)


class WritingOutputV1(ContractModel):
    title: str = Field(min_length=1, max_length=200)
    lead: str = Field(min_length=1, max_length=1000)
    paragraphs: tuple[DraftParagraphV1, ...] = Field(min_length=1, max_length=30)
    category_keys: tuple[Category, ...] = Field(min_length=1)
    audiences: tuple[str, ...] = ()
    importance: int = Field(ge=1, le=5)
    previous_comparison: str = Field(min_length=1, max_length=3000)
    competitor_comparison: str = Field(min_length=1, max_length=3000)
    risk_flags: tuple[str, ...] = ()


class ResearchRequestV1(ContractModel):
    item_id: UUID
    item_version: int = Field(ge=1)
    relation: Literal["previous", "competitor"]
    query: str
    approved_source_keys: tuple[str, ...]


class ReviewChecklistV1(ContractModel):
    official_primary_source: StrictBool
    facts_match_evidence: StrictBool
    no_unattributed_claims: StrictBool
    original_expression_not_copied: StrictBool
    quotes_are_necessary_and_minimal: StrictBool
    source_links_present: StrictBool
    media_rights_verified_or_no_media: StrictBool
    terms_and_robots_clear: StrictBool
    personal_data_checked: StrictBool
    wordpress_preview_checked: StrictBool


class ReviewRequestV1(ContractModel):
    expected_version: int = Field(ge=1)
    draft_id: UUID
    decision: Literal["approve", "needs_changes", "reject"]
    checklist: ReviewChecklistV1
    comment: str | None = Field(default=None, max_length=2000)


class ManualDraftRequestV1(ContractModel):
    expected_version: int = Field(ge=1)
    output: WritingOutputV1
