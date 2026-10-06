"""Source-grounded topic and comparison audit snapshots."""

from typing import Literal
from uuid import UUID

from app.contracts.base import ContractModel


class TopicEvidenceV1(ContractModel):
    field: Literal["title", "body"]
    start: int
    end: int
    quote: str


class TopicFacetV1(ContractModel):
    dimension: str
    key: str
    label: str
    evidence: tuple[TopicEvidenceV1, ...]


class ArticleTopicV1(ContractModel):
    item_id: UUID
    item_version: int
    source_url: str
    extraction_hash: str
    policy_version: str
    input_hash: str
    method: str = "source_keyword_rules"
    topic_label: str
    facets: tuple[TopicFacetV1, ...]
    unknown_dimensions: tuple[str, ...]


class SelectionCheckV1(ContractModel):
    required: bool = False
    criterion: str
    result: Literal["pass", "fail", "unknown"]
    target_values: tuple[str, ...]
    candidate_values: tuple[str, ...]
    explanation: str


class FeatureSideV1(ContractModel):
    values: tuple[str, ...] = ()
    fact_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    conditions: tuple[str, ...] = ()


class FeatureComparisonV1(ContractModel):
    axis: str
    label: str
    target: FeatureSideV1
    candidate: FeatureSideV1
    result: Literal["common", "different", "partial_overlap", "unknown", "not_comparable"]
    explanation: str


class CandidateAssessmentV1(ContractModel):
    candidate_topic: ArticleTopicV1
    relation: Literal["previous", "competitor"]
    decision: Literal["eligible", "rejected"]
    reason_codes: tuple[str, ...]
    selection_checks: tuple[SelectionCheckV1, ...]
    shared_feature_axes: tuple[str, ...]
    features: tuple[FeatureComparisonV1, ...]
    score: int
    retrieval_score: int | None = None
    retrieval_rank: int | None = None
    evidence_package_id: UUID | None = None
    evidence_hash: str | None = None


class ComparisonAnalysisV1(ContractModel):
    item_id: UUID
    item_version: int
    policy_version: str
    target_topic: ArticleTopicV1
    selection_criteria: tuple[str, ...]
    candidates: tuple[CandidateAssessmentV1, ...]
    selected_item_ids: tuple[UUID, ...] = ()
    scope: str = "登録済みの承認済み一次情報と指定された参照記事の範囲"
