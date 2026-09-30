from typing import Protocol

from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.envelope import ContractEnvelope


class WritingPort(Protocol):
    def write(
        self, package: ContractEnvelope[ArticlePackageV1]
    ) -> ContractEnvelope[ArticleDraftV1]: ...
