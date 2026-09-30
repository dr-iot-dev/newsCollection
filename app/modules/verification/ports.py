from typing import Protocol

from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.envelope import ContractEnvelope
from app.contracts.verification_v1 import VerificationReportV1


class VerificationPort(Protocol):
    def verify(
        self, draft: ContractEnvelope[ArticleDraftV1]
    ) -> ContractEnvelope[VerificationReportV1]: ...
