from uuid import UUID

from pydantic import Field

from app.contracts.base import ContractModel


class PublicationPackageV1(ContractModel):
    item_id: UUID
    draft_id: UUID
    # Review ID for producer=review; VerificationRun ID for producer=verification.
    approval_id: UUID
    sanitized_content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    target: str
    cms_category_ids: tuple[int, ...] = ()
    cms_tag_ids: tuple[int, ...] = ()
