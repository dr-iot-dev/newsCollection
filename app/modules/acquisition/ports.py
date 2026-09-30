from typing import Protocol
from uuid import UUID

from app.contracts.acquisition_v1 import AcquisitionResultV1
from app.contracts.envelope import ContractEnvelope


class AcquisitionPort(Protocol):
    def acquire(self, source_id: UUID) -> ContractEnvelope[AcquisitionResultV1]: ...
