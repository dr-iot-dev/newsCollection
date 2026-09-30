from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.base import ContractModel
from app.contracts.envelope import ContractEnvelope
from app.infrastructure.db.models import ModuleMessage

PayloadT = TypeVar("PayloadT", bound=ContractModel)


class ModuleMessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue_once(
        self,
        envelope: ContractEnvelope[PayloadT],
        *,
        consumer: str,
        status: str = "pending",
    ) -> ModuleMessage:
        existing = (
            self._session.query(ModuleMessage)
            .filter_by(consumer=consumer, payload_hash=envelope.payload_hash)
            .one_or_none()
        )
        if existing is not None:
            return existing
        message = ModuleMessage(
            message_id=envelope.message_id,
            contract_type=envelope.contract_type,
            schema_version=envelope.schema_version,
            correlation_id=envelope.correlation_id,
            producer=envelope.producer,
            consumer=consumer,
            payload_json=envelope.payload.model_dump(mode="json"),
            payload_hash=envelope.payload_hash,
            status=status,
            available_at=envelope.created_at,
        )

        try:
            with self._session.begin_nested():
                self._session.add(message)
                self._session.flush()
        except IntegrityError:
            duplicate = (
                self._session.query(ModuleMessage)
                .filter_by(consumer=consumer, payload_hash=envelope.payload_hash)
                .one()
            )
            return duplicate
        return message
