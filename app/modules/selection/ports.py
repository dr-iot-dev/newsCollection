from typing import Protocol

from app.contracts.candidate_v1 import CandidateDecisionV1
from app.contracts.envelope import ContractEnvelope
from app.contracts.evidence_v1 import EvidencePackageV1


class SelectionPort(Protocol):
    def select(
        self, evidence: ContractEnvelope[EvidencePackageV1]
    ) -> ContractEnvelope[CandidateDecisionV1]: ...
