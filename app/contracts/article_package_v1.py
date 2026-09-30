from uuid import UUID

from app.contracts.base import ContractModel


class SourceReferenceV1(ContractModel):
    reference_id: UUID
    fact_ids: tuple[UUID, ...]


class ArticlePackageV1(ContractModel):
    item_id: UUID
    revision: int
    topic: str
    verified_fact_ids: tuple[UUID, ...]
    comparison_dataset_id: UUID
    source_references: tuple[SourceReferenceV1, ...]
    uncertainties: tuple[str, ...] = ()
    writing_policy_version: str
