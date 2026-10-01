from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import LegalStatus, Source, SourceCursor, SourceType
from app.sources.config import DefaultsConfig, SourceConfig, SourcesFile


@dataclass(frozen=True)
class SyncAction:
    key: str
    action: str
    legal_status: str


def _connector_config(source: SourceConfig, defaults: DefaultsConfig) -> dict[str, object]:
    effective = source.model_dump(mode="json", exclude={"key", "name", "type", "enabled"})
    for field in (
        "interval_minutes",
        "timeout_seconds",
        "max_response_bytes",
        "user_agent",
        "language_hint",
    ):
        if effective.get(field) is None:
            effective[field] = getattr(defaults, field)
    return effective


def sync_sources(session: Session, config: SourcesFile, *, dry_run: bool) -> list[SyncAction]:
    existing = {row.key: row for row in session.scalars(select(Source)).all()}
    actions: list[SyncAction] = []
    now = datetime.now(UTC)
    for source_config in config.sources:
        legal_status = source_config.legal.effective_status(now)
        action = "create" if source_config.key not in existing else "update"
        row = existing.get(source_config.key)
        gate_cursor = session.get(SourceCursor, row.id) if row is not None else None
        gate = gate_cursor.cursor_json.get("web_gate", {}) if gate_cursor else {}
        if gate.get("blocked") and legal_status == "approved":
            blocked_at = datetime.fromisoformat(gate["checked_at"])
            reviewed_dates = [
                source_config.legal.terms_reviewed_at,
                source_config.legal.robots_reviewed_at,
            ]
            if any(
                value is None
                or (value.replace(tzinfo=UTC) if value.tzinfo is None else value) <= blocked_at
                for value in reviewed_dates
            ):
                legal_status = "pending"
        actions.append(SyncAction(source_config.key, action, legal_status))
        if dry_run:
            continue
        if row is None:
            row = Source(key=source_config.key)
            session.add(row)
        row.type = SourceType(source_config.type)
        row.name = source_config.name
        row.config = _connector_config(source_config, config.defaults)
        row.enabled = source_config.enabled
        row.legal_status = LegalStatus(legal_status)
        row.terms_url = source_config.legal.terms_url
        row.terms_checked_at = source_config.legal.terms_reviewed_at
    if not dry_run:
        session.flush()
    return actions
