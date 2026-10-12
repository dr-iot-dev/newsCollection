"""Read-only export of supported-target CMS history, with no CMS client."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.article_package_v1 import ArticlePackageV1
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import ArticleDraft, ArticlePackage, Publication
from app.orchestration.draft_exports import producer_identity
from app.orchestration.source_sets import package_source_set
from nw_generation.protocol import atomic_write, canonical, object_hash


def export_history(session: Session, settings: Settings, target_id: str, path: Path) -> int:
    if re.fullmatch(r"wordpress:[0-9a-f]{64}", target_id) is None:
        raise EditorialError("HISTORY_TARGET_INVALID")
    records: list[dict[str, Any]] = []
    producer = producer_identity(settings)
    rows = session.scalars(
        select(Publication)
        .where(Publication.target == target_id)
        .order_by(Publication.created_at, Publication.id)
    ).all()
    for row in rows:
        draft = session.get(ArticleDraft, row.draft_id)
        if draft is None or not row.payload_json:
            raise EditorialError("HISTORY_PAYLOAD_REQUIRED")
        payload = dict(row.payload_json)
        # Historical public/trash rows are suppressed by the receiver. Payload
        # retains draft-only semantics because the new application never publishes.
        payload["status"] = "draft"
        from app.orchestration.editorial import checked_payload

        package_row = session.get(ArticlePackage, draft.article_package_id)
        if package_row is None:
            raise EditorialError("HISTORY_PACKAGE_REQUIRED")
        source = package_source_set(checked_payload(package_row, ArticlePackageV1))
        records.append(
            {
                "target_id": target_id,
                "producer_id": producer,
                "article_id": str(draft.item_id),
                "draft_id": str(draft.id),
                "revision": draft.revision,
                "artifact_revision": 1,
                "operation_key": row.idempotency_key,
                "payload": payload,
                "payload_hash": object_hash(payload),
                "state": row.state,
                "remote_post_id": row.remote_post_id,
                "remote_hash": row.remote_hash,
                "remote_status": row.remote_status,
                "source_set_hash": source,
            }
        )
    atomic_write(path, canonical({"schema_version": "1.0", "deliveries": records}))
    return len(records)
