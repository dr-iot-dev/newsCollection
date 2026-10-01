"""Transactional outbox consumers for extraction and duplicate detection."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AnyHttpUrl
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.contracts.acquisition_v1 import AcquisitionResultV1
from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.contracts.evidence_v1 import EvidencePackageV1
from app.infrastructure.db.models import (
    DuplicateDecision,
    ExtractionResult,
    Item,
    ItemStatus,
    ItemVersion,
    LegalStatus,
    ModuleMessage,
    RawSnapshot,
    Source,
)
from app.infrastructure.db.repositories.audit import AuditEventWriter
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.modules.acquisition.service import source_config
from app.modules.deduplication.service import POLICY_VERSION, compare, simhash
from app.modules.extraction.service import extract_content
from app.sources.config import WebSource


def messages(session: Session, consumer: str, limit: int) -> list[ModuleMessage]:
    return list(
        session.scalars(
            select(ModuleMessage)
            .where(
                ModuleMessage.consumer == consumer,
                ModuleMessage.status == "pending",
                ModuleMessage.available_at <= datetime.now(UTC),
            )
            .order_by(ModuleMessage.created_at, ModuleMessage.message_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )


def lock_item(session: Session, item_id: UUID) -> Item | None:
    item = session.get(Item, item_id)
    if item is None:
        return None
    # Collectors lock a source before changing its articles. Use the same order.
    session.scalar(select(Source).where(Source.id == item.source_id).with_for_update())
    return session.scalar(
        select(Item)
        .where(Item.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def audit(
    session: Session, item: Item, action: str, trace_id: UUID, after: dict[str, object]
) -> None:
    AuditEventWriter(session).append(
        actor_type="system",
        actor_id="phase2",
        action=action,
        entity_type="item",
        entity_id=str(item.id),
        trace_id=str(trace_id),
        after=after,
    )


def extract_messages(session: Session, limit: int) -> int:
    handled = 0
    for message in messages(session, "extraction", limit):
        payload = AcquisitionResultV1.model_validate(message.payload_json)
        if canonical_payload_hash(message.payload_json) != message.payload_hash:
            raise ValueError("OUTBOX_HASH_MISMATCH")
        snapshot = session.get(RawSnapshot, payload.snapshot_id)
        if (
            snapshot is None
            or snapshot.source_id != payload.source_id
            or snapshot.body_sha256 != payload.content_sha256
        ):
            raise ValueError("SNAPSHOT_REFERENCE_MISMATCH")
        versions = list(
            session.scalars(
                select(ItemVersion)
                .join(Item, Item.id == ItemVersion.item_id)
                .where(
                    ItemVersion.snapshot_id == snapshot.id, Item.version == ItemVersion.version_no
                )
                .order_by(ItemVersion.item_id)
            )
        )
        for version in versions:
            item = lock_item(session, version.item_id)
            assert item is not None
            if item.version != version.version_no:
                continue
            existing = session.scalar(
                select(ExtractionResult).where(
                    ExtractionResult.item_id == item.id,
                    ExtractionResult.revision == version.version_no,
                )
            )
            if existing:
                continue
            source = session.get(Source, item.source_id)
            assert source is not None
            config = source_config(source)
            web = isinstance(config, WebSource)
            content = extract_content(
                item_id=item.id,
                item_version=version.version_no,
                snapshot_id=snapshot.id,
                url=item.canonical_url,
                title=version.title,
                body=snapshot.body_text or "" if web else version.content_text,
                published_at=version.published_at,
                language=item.language,
                is_html=web,
                timezone_hint=config.timezone_hint,
                selectors=config.selectors if isinstance(config, WebSource) else None,
                allowed_hosts=config.allowed_hosts if isinstance(config, WebSource) else None,
            )
            dumped = content.model_dump(mode="json")
            session.add(
                ExtractionResult(
                    item_id=item.id,
                    revision=version.version_no,
                    snapshot_id=snapshot.id,
                    payload_json=dumped,
                    payload_hash=canonical_payload_hash(dumped),
                    body_sha256=content.body_sha256,
                    canonical_url=str(content.canonical_url),
                )
            )
            item.status = ItemStatus.EXTRACTED
            signature = simhash(content.title + "\n" + content.body)
            item.simhash64 = signature if signature < 2**63 else signature - 2**64
            envelope = ContractEnvelope[NormalizedContentV1].build(
                content,
                contract_type="NormalizedContent",
                producer="extraction",
                producer_version="0.2.0",
                correlation_id=message.correlation_id,
            )
            ModuleMessageRepository(session).enqueue_once(envelope, consumer="deduplication")
            audit(
                session,
                item,
                "item.extracted",
                message.correlation_id,
                {"revision": item.version, "quality_score": content.quality_score},
            )
        message.status, message.processed_at = "processed", datetime.now(UTC)
        handled += 1
    session.flush()
    return handled


def dedup_messages(session: Session, limit: int) -> int:
    handled = 0
    for message in messages(session, "deduplication", limit):
        content = NormalizedContentV1.model_validate(message.payload_json)
        if canonical_payload_hash(message.payload_json) != message.payload_hash:
            raise ValueError("OUTBOX_HASH_MISMATCH")
        item = lock_item(session, content.item_id)
        if item is None or item.version != content.item_version:
            message.status, message.processed_at = "processed", datetime.now(UTC)
            handled += 1
            continue
        source = session.get(Source, item.source_id)
        assert source is not None
        rights_ok = (
            source.legal_status == LegalStatus.APPROVED
            and source_config(source).legal.effective_status() == "approved"
        )
        item.duplicate_of_id = None
        # A changed representative cannot silently keep earlier group memberships.
        if item.version > 1:
            for dependent in session.scalars(select(Item).where(Item.duplicate_of_id == item.id)):
                dependent.duplicate_of_id, dependent.status = None, ItemStatus.REVIEW_PENDING
                audit(
                    session,
                    dependent,
                    "item.duplicate_invalidated",
                    message.correlation_id,
                    {"representative_id": str(item.id), "representative_revision": item.version},
                )
        candidate_rows = session.execute(
            select(ExtractionResult, Item)
            .join(Item, Item.id == ExtractionResult.item_id)
            .where(
                Item.id != item.id,
                ExtractionResult.revision == Item.version,
                Item.duplicate_of_id.is_(None),
                Item.status == ItemStatus.DEDUPED,
            )
            .order_by(Item.created_at, Item.id)
        ).all()
        best = None
        best_candidate = None
        for extracted, candidate in candidate_rows:
            other = NormalizedContentV1.model_validate(extracted.payload_json)
            match = compare(content, other)
            decision = match.decision if content.quality_score >= 0.6 and rights_ok else "review"
            session.add(
                DuplicateDecision(
                    item_id=item.id,
                    revision=item.version,
                    candidate_id=candidate.id,
                    candidate_revision=candidate.version,
                    decision=decision,
                    score=Decimal(str(match.score)),
                    reasons=match.reasons,
                    policy_version=POLICY_VERSION,
                )
            )
            if match.score < 0.80:
                continue
            if best is None or (decision == "duplicate", match.score) > (
                best[0] == "duplicate",
                best[1],
            ):
                best, best_candidate = (decision, match.score), candidate
        if best is None:
            session.add(
                DuplicateDecision(
                    item_id=item.id,
                    revision=item.version,
                    candidate_id=None,
                    decision="separate",
                    score=Decimal("0"),
                    reasons={"no_candidate_above_threshold": True},
                    policy_version=POLICY_VERSION,
                )
            )
        review = (
            content.quality_score < 0.6
            or not rights_ok
            or (best is not None and best[0] == "review")
        )
        if best and best[0] == "duplicate" and best_candidate is not None:
            item.duplicate_of_id = best_candidate.id
        item.status = ItemStatus.REVIEW_PENDING if review else ItemStatus.DEDUPED
        audit(
            session,
            item,
            "item.deduplicated",
            message.correlation_id,
            {
                "revision": item.version,
                "status": item.status.value,
                "duplicate_of_id": str(item.duplicate_of_id) if item.duplicate_of_id else None,
            },
        )
        if not review and item.duplicate_of_id is None:
            evidence = EvidencePackageV1(
                item_id=item.id,
                item_version=item.version,
                canonical_url=AnyHttpUrl(content.canonical_url),
                title=content.title,
                published_at=content.published_at,
                language=content.language,
                facts=(),
                quality_score=content.quality_score,
            )
            envelope = ContractEnvelope[EvidencePackageV1].build(
                evidence,
                contract_type="EvidencePackage",
                producer="deduplication",
                producer_version="0.2.0",
                correlation_id=message.correlation_id,
            )
            # Phase 3 will consume these messages to extract facts.
            ModuleMessageRepository(session).enqueue_once(envelope, consumer="facts")
        message.status, message.processed_at = "processed", datetime.now(UTC)
        handled += 1
        session.flush()
    return handled


def process_phase2(session: Session, *, limit: int = 100) -> dict[str, int]:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if session.get_bind().dialect.name == "postgresql":
        # Serialize representative selection across CLI and scheduler processes.
        session.execute(text("SELECT pg_advisory_xact_lock(2026093002)"))
    return {
        "extraction": extract_messages(session, limit),
        "deduplication": dedup_messages(session, limit),
    }
