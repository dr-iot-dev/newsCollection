import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from app.contracts.base import ContractModel

PayloadT = TypeVar("PayloadT", bound=ContractModel)


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ContractEnvelope(ContractModel, Generic[PayloadT]):
    contract_type: str = Field(min_length=1, max_length=100)
    schema_version: str = Field(pattern=r"^[1-9][0-9]*\.[0-9]+$")
    message_id: UUID
    correlation_id: UUID
    producer: str = Field(min_length=1, max_length=50)
    producer_version: str = Field(min_length=1, max_length=50)
    created_at: datetime
    payload_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    payload: PayloadT

    @model_validator(mode="after")
    def validate_payload_hash(self) -> "ContractEnvelope[PayloadT]":
        actual = canonical_payload_hash(self.payload.model_dump(mode="json"))
        if actual != self.payload_hash:
            raise ValueError("payload_hash does not match canonical payload")
        return self

    @classmethod
    def build(
        cls,
        payload: PayloadT,
        *,
        contract_type: str,
        producer: str,
        producer_version: str,
        correlation_id: UUID | None = None,
        schema_version: str = "1.0",
    ) -> "ContractEnvelope[PayloadT]":
        dumped = payload.model_dump(mode="json")
        return cls(
            contract_type=contract_type,
            schema_version=schema_version,
            message_id=uuid4(),
            correlation_id=correlation_id or uuid4(),
            producer=producer,
            producer_version=producer_version,
            created_at=datetime.now(UTC),
            payload_hash=canonical_payload_hash(dumped),
            payload=payload,
        )
