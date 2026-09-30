from typing import Protocol

from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.candidate_v1 import CandidateDecisionV1
from app.contracts.envelope import ContractEnvelope


class ComparisonPort(Protocol):
    def research(
        self, decision: ContractEnvelope[CandidateDecisionV1]
    ) -> ContractEnvelope[ArticlePackageV1]: ...
