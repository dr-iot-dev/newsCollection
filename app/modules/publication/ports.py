from typing import Protocol

from app.contracts.envelope import ContractEnvelope
from app.contracts.publication_v1 import PublicationPackageV1


class PublicationPort(Protocol):
    def create_draft(self, package: ContractEnvelope[PublicationPackageV1]) -> str: ...
