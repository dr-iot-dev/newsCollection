from typing import Any

from sqlalchemy.orm import Session

from app.infrastructure.db.models import AuditEvent


class AuditEventWriter:
    """Append-only audit writer. Deliberately exposes no update or delete method."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        trace_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            trace_id=trace_id,
            before_json=before,
            after_json=after,
        )
        self._session.add(event)
        self._session.flush()
        return event
