from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.acquisition_v1 import AcquisitionResultV1
from app.contracts.envelope import ContractEnvelope


def acquisition() -> AcquisitionResultV1:
    return AcquisitionResultV1(
        snapshot_id=uuid4(),
        source_id=uuid4(),
        final_url="https://example.com/news/1",
        fetched_at=datetime.now(UTC),
        content_sha256="a" * 64,
    )


def test_envelope_builds_and_verifies_hash() -> None:
    envelope = ContractEnvelope.build(
        acquisition(),
        contract_type="AcquisitionResult",
        producer="acquisition",
        producer_version="0.1.0",
    )
    parsed = ContractEnvelope[AcquisitionResultV1].model_validate(envelope.model_dump())
    assert parsed.payload.snapshot_id == envelope.payload.snapshot_id
    assert parsed.payload_hash.startswith("sha256:")


def test_tampered_payload_is_rejected() -> None:
    envelope = ContractEnvelope.build(
        acquisition(),
        contract_type="AcquisitionResult",
        producer="acquisition",
        producer_version="0.1.0",
    )
    value = envelope.model_dump(mode="json")
    value["payload"]["content_sha256"] = "b" * 64
    with pytest.raises(ValidationError, match="payload_hash"):
        ContractEnvelope[AcquisitionResultV1].model_validate(value)


def test_contracts_forbid_unknown_fields() -> None:
    value = acquisition().model_dump()
    value["cookie"] = "must-not-pass"
    with pytest.raises(ValidationError):
        AcquisitionResultV1.model_validate(value)


def test_schema_disallows_additional_properties() -> None:
    assert AcquisitionResultV1.model_json_schema()["additionalProperties"] is False
