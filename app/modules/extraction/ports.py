from typing import Protocol
from uuid import UUID

from app.contracts.envelope import ContractEnvelope
from app.contracts.evidence_v1 import EvidencePackageV1


class ExtractionPort(Protocol):
    def extract(self, snapshot_id: UUID) -> ContractEnvelope[EvidencePackageV1]: ...
