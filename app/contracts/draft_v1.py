from uuid import UUID

from pydantic import Field

from app.contracts.base import ContractModel


class ParagraphFactMapV1(ContractModel):
    paragraph: int = Field(ge=0)
    fact_ids: tuple[UUID, ...]


class ArticleDraftV1(ContractModel):
    draft_id: UUID
    item_id: UUID
    article_package_id: UUID
    revision: int = Field(ge=1)
    title: str
    lead: str
    body_markdown: str
    category_keys: tuple[str, ...]
    tags: tuple[str, ...] = ()
    paragraph_facts: tuple[ParagraphFactMapV1, ...]
    risk_flags: tuple[str, ...] = ()
    writer_profile_key: str
