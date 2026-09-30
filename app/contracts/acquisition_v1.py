from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from app.contracts.base import ContractModel


class AcquisitionResultV1(ContractModel):
    snapshot_id: UUID
    source_id: UUID
    final_url: AnyHttpUrl
    fetched_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
