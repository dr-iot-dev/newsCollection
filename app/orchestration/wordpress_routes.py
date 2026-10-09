"""Explicit, transactional migration of a CMS destination's existing history."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.contracts.publication_v1 import PublicationPackageV1
from app.contracts.wordpress_v1 import WordPressPayloadV1
from app.core.editorial import EditorialError
from app.infrastructure.db.models import ArticleDraft, Publication, SourceSetClaim
from app.infrastructure.db.repositories.audit import AuditEventWriter
from app.modules.publication.service import idempotency_key


def migrate_wordpress_history(
    session: Session, old_target: str, new_target: str, *, apply: bool = False,
) -> dict[str, Any]:
    """Caller owns the transaction; drafts, payloads, approvals and images are retained."""
    if old_target == new_target:
        raise EditorialError("WORDPRESS_MIGRATION_SAME_TARGET", 422)
    if apply and session.get_bind().dialect.name == "postgresql":
        session.execute(text(
            "LOCK TABLE publications, source_set_claims IN SHARE ROW EXCLUSIVE MODE"
        ))
    rows = list(session.scalars(
        select(Publication).where(Publication.target == old_target).with_for_update()
    ))
    claims = list(session.scalars(
        select(SourceSetClaim).where(SourceSetClaim.scope == old_target).with_for_update()
    ))
    if not rows and not claims:
        return {"publications": 0, "source_claims": 0, "applied": False}
    if (
        session.scalar(select(Publication.id).where(Publication.target == new_target))
        or session.scalar(select(SourceSetClaim.id).where(SourceSetClaim.scope == new_target))
    ):
        raise EditorialError("WORDPRESS_MIGRATION_TARGET_NOT_EMPTY")
    changes = []
    for row in rows:
        draft = session.get(ArticleDraft, row.draft_id)
        if draft is None or draft.item_id != row.item_id:
            raise EditorialError("WORDPRESS_MIGRATION_DRAFT_INVALID")
        if row.idempotency_key != idempotency_key(old_target, row.item_id, draft.revision):
            raise EditorialError("WORDPRESS_MIGRATION_KEY_INVALID")
        if row.payload_json is not None:
            WordPressPayloadV1.model_validate(row.payload_json)
            if canonical_payload_hash(row.payload_json) != row.payload_hash:
                raise EditorialError("WORDPRESS_MIGRATION_PAYLOAD_INVALID")
        package = None
        if row.package_json is not None:
            envelope = ContractEnvelope[PublicationPackageV1].model_validate(row.package_json)
            if envelope.payload.target != old_target:
                raise EditorialError("WORDPRESS_MIGRATION_PACKAGE_INVALID")
            package = deepcopy(row.package_json)
            package["payload"]["target"] = new_target
            package["payload_hash"] = canonical_payload_hash(package["payload"])
            ContractEnvelope[PublicationPackageV1].model_validate(package)
        changes.append((row, idempotency_key(new_target, row.item_id, draft.revision), package))
    row_ids = {row.id for row in rows}
    if any(claim.publication_id and claim.publication_id not in row_ids for claim in claims):
        raise EditorialError("WORDPRESS_MIGRATION_CLAIM_INVALID")
    if apply:
        trace = str(uuid4())
        audit = AuditEventWriter(session)
        for row, new_key, package in changes:
            before = {"target": row.target, "idempotency_key": row.idempotency_key}
            row.target, row.idempotency_key = new_target, new_key
            row.package_json = package
            audit.append(
                actor_type="operator", actor_id="wordpress-route-migration",
                action="wordpress.target_migrated", entity_type="publication",
                entity_id=str(row.id), trace_id=trace, before=before,
                after={"target": new_target, "idempotency_key": new_key,
                       "remote_post_id": row.remote_post_id},
            )
        for claim in claims:
            claim.scope = new_target
        session.flush()
    return {"old_target": old_target, "new_target": new_target, "publications": len(rows),
            "source_claims": len(claims), "applied": apply}
