from typing import Protocol
from uuid import UUID

from app.contracts.acquisition_v1 import AcquisitionResultV1
from app.contracts.editorial_v1 import ResearchRequestV1
from app.contracts.envelope import ContractEnvelope


class AcquisitionPort(Protocol):
    def acquire(self, source_id: UUID) -> ContractEnvelope[AcquisitionResultV1]: ...


class ResearchAcquisitionPort(Protocol):
    def request_search(self, request: "ResearchRequestV1") -> None: ...
