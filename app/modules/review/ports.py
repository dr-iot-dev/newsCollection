from typing import Protocol
from uuid import UUID

from app.contracts.envelope import ContractEnvelope
from app.contracts.publication_v1 import PublicationPackageV1


class ReviewPort(Protocol):
    def approve(
        self, draft_id: UUID, reviewer_id: UUID
    ) -> ContractEnvelope[PublicationPackageV1]: ...
