"""Publication requests and CMS payloads contain no source text or credentials."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool

from app.contracts.base import ContractModel


class WordPressRequestV1(ContractModel):
    expected_version: int = Field(ge=1)
    draft_id: UUID


class PublishApprovalRequestV1(WordPressRequestV1):
    publication_id: UUID
    confirm_publish: StrictBool


class PublishRequestV1(WordPressRequestV1):
    publication_id: UUID
    publish_approval_id: UUID


class WordPressPayloadV1(ContractModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=200000)
    excerpt: str = Field(max_length=2000)
    slug: str = Field(pattern=r"^news-[a-f0-9]{64}$")
    status: Literal["draft"] = "draft"
    categories: tuple[Annotated[int, Field(ge=1, strict=True)], ...] = Field(min_length=1)
    tags: tuple[Annotated[int, Field(ge=1, strict=True)], ...] = ()
    featured_media: int = Field(default=0, ge=0, strict=True, exclude_if=lambda value: value == 0)
