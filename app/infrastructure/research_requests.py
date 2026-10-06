from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.editorial_v1 import ResearchRequestV1
from app.contracts.envelope import ContractEnvelope
from app.infrastructure.db.repositories.messages import ModuleMessageRepository


class QueuedResearchAcquisition:
    """Acquisition port adapter: record bounded source search requests for fulfillment."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def request_search(self, request: ResearchRequestV1) -> UUID:
        message = ModuleMessageRepository(self.session).enqueue_once(
            ContractEnvelope.build(
                request,
                contract_type="ResearchRequest",
                producer="comparison",
                producer_version="0.3.0",
            ),
            consumer="acquisition_research",
        )
        return message.message_id
