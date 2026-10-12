"""Category-led pair discovery contracts, separate from publication approvals."""

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from app.contracts.base import ContractModel

POLICY = "comparison-pair-discovery-v3-10-pairs"
PREPROCESSING = "comparison-body-v1"
KEYWORD_POLICY = "category-distinction-v3-fifty"
KEYWORD_TARGET = 50
SEARCH_POLICY = "per-keyword-results-v1"
SEARCH_RESULTS_PER_KEYWORD = 150
ACQUISITION_POLICY = "product-service-titles-v6-initial-category-text-no-tag"


class PairDiscoveryRequest(ContractModel):
    run_id: UUID = Field(default_factory=uuid4)
    source_key: str = Field(min_length=1, max_length=100)
    initial_count: int = Field(default=10, ge=3, le=20)
    maximum_documents: int = Field(default=100, ge=3, le=100)
    pair_limit: Literal[10] = 10
    mode: Literal["shadow"] = "shadow"


class PairDocument(ContractModel):
    item_id: UUID
    item_version: int = Field(ge=1)
    snapshot_id: UUID
    source_id: UUID
    url: str
    title: str
    body: str = Field(min_length=1)
    body_hash: str
    # Initial-list provenance only; search articles need no category tag.
    category_proof: str = ""

    @model_validator(mode="after")
    def hash_matches(self) -> "PairDocument":
        if hashlib.sha256(self.body.encode()).hexdigest() != self.body_hash:
            raise ValueError("Document body hash mismatch")
        return self


class SourceQuote(ContractModel):
    item_id: UUID
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str = Field(min_length=1)


class SearchTerm(ContractModel):
    key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    aliases: tuple[str, ...] = Field(default=(), max_length=12)
    evidence: tuple[SourceQuote, ...] = Field(min_length=1)
    distinction_reason: str = Field(default="", max_length=1000)


class CategoryKeywords(ContractModel):
    terms: tuple[SearchTerm, ...] = Field(max_length=KEYWORD_TARGET)
    reason: str


class ComparisonAxis(SearchTerm):
    question: str = Field(min_length=1, max_length=500)


class PairProduct(ContractModel):
    item_id: UUID
    name: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    evidence: tuple[SourceQuote, ...] = Field(min_length=1)


class PairPlan(ContractModel):
    comparable: bool
    purpose: str
    reason: str
    products: tuple[PairProduct, ...]
    axes: tuple[ComparisonAxis, ...] = Field(max_length=12)


class FeatureCell(ContractModel):
    item_id: UUID
    axis_key: str
    status: Literal[
        "supported", "not_supported", "conditional", "planned", "unknown", "incomparable"
    ]
    answer: str
    conditions: str
    evidence: tuple[SourceQuote, ...]


class DocumentFeatures(ContractModel):
    product: PairProduct
    cells: tuple[FeatureCell, ...]


class TripleReview(ContractModel):
    same_selection_task: bool
    evidence_valid: bool
    conditions_preserved: bool
    reason: str
    valid_axis_keys: tuple[str, ...]


class PairDistance(ContractModel):
    left: UUID
    right: UUID
    distance: float = Field(ge=0, le=2, allow_inf_nan=False)
    rank: int = Field(ge=1)


class PairEvent(ContractModel):
    run_id: UUID
    sequence: int = Field(ge=1)
    step: int = Field(ge=1, le=12)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any]


class PairDiscoveryState(ContractModel):
    request: PairDiscoveryRequest
    policy: str = POLICY
    fingerprint: str
    status: Literal[
        "running",
        "selection_passed",
        "exhausted",
        "paused_budget",
        "waiting_retry",
        "insufficient_pairs",
        "insufficient_sources",
        "insufficient_keywords",
        "failed_configuration",
    ] = "running"
    reason: str = ""
    initial: tuple[PairDocument, ...] = ()
    keywords: CategoryKeywords | None = None
    group_a: tuple[PairDocument, ...] = ()
    acquisition: dict[str, Any] = Field(default_factory=dict)
    embeddings: dict[str, Any] = Field(default_factory=dict)
    stages: dict[str, Any] = Field(default_factory=dict)
    distances: tuple[PairDistance, ...] = ()
    completed_pairs: int = Field(default=0, ge=0, le=10)
    pair_results: tuple[dict[str, Any], ...] = ()
    selected: dict[str, Any] | None = None
    sequence: int = 0
    external_calls: int = 0
    ai_calls: int = 0
    ai_attempt_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def terminal_invariants(self) -> "PairDiscoveryState":
        if self.completed_pairs != len(self.pair_results):
            raise ValueError("Completed pair count must match recorded results")
        if self.status == "exhausted" and (self.completed_pairs != 10 or self.selected is not None):
            raise ValueError("Search exhaustion requires ten completed unsuccessful pairs")
        if self.status == "selection_passed" and self.selected is None:
            raise ValueError("Successful selection requires its frozen comparison")
        return self
