from uuid import UUID

from pydantic import AnyHttpUrl

from app.contracts.base import ContractModel
from app.contracts.comparison_analysis_v1 import ArticleTopicV1
from app.contracts.comparison_v1 import ComparisonDatasetV1
from app.contracts.facts_v1 import VerifiedFactV1


class SourceReferenceV1(ContractModel):
    url: AnyHttpUrl | None = None
    reference_id: UUID
    fact_ids: tuple[UUID, ...]


class ArticlePackageV1(ContractModel):
    request_hash: str = ""
    item_version: int = 1
    candidate_id: UUID | None = None
    facts: tuple[VerifiedFactV1, ...] = ()
    comparison: ComparisonDatasetV1 | None = None
    item_id: UUID
    revision: int
    topic: str
    topic_profile: ArticleTopicV1 | None = None
    verified_fact_ids: tuple[UUID, ...]
    comparison_dataset_id: UUID
    source_references: tuple[SourceReferenceV1, ...]
    uncertainties: tuple[str, ...] = ()
    writing_policy_version: str
