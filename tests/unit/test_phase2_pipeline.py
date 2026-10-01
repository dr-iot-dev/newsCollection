import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import (
    DuplicateDecision,
    ExtractionResult,
    Item,
    ItemStatus,
    ModuleMessage,
)
from app.modules.acquisition.service import collect_source
from app.orchestration.phase2 import process_phase2
from tests.unit.test_acquisition_service import RSS, count, feed_factory


def collect(session, body=RSS):
    assert (
        collect_source(
            session, "vendor-official-feed", force=True, http_factory=feed_factory(body)
        ).status
        == "success"
    )
    session.commit()


def test_short_feed_is_review_pending_and_pipeline_is_idempotent(
    acquisition_session: Session,
) -> None:
    session = acquisition_session
    collect(session)
    assert process_phase2(session) == {"extraction": 1, "deduplication": 1}
    session.commit()
    assert session.scalars(select(Item.status)).one() == ItemStatus.REVIEW_PENDING
    assert count(session, ExtractionResult) == count(session, DuplicateDecision) == 1
    assert not list(session.scalars(select(ModuleMessage).where(ModuleMessage.consumer == "facts")))
    assert process_phase2(session) == {"extraction": 0, "deduplication": 0}


def test_identical_articles_group_without_deletion_and_updated_representative_invalidates_group(
    acquisition_session: Session,
) -> None:
    session = acquisition_session
    text = (
        b"The manufacturer released a gateway with a documented local integration interface. " * 8
    )
    body = RSS.replace(b"Feature one", text)
    collect(session, body)
    process_phase2(session)
    session.commit()
    representative = session.scalars(select(Item)).one()
    second = body.replace(b"release-1", b"release-2").replace(b"/news/one", b"/news/two")
    collect(session, second)
    process_phase2(session)
    session.commit()
    duplicate = session.scalars(select(Item).where(Item.id != representative.id)).one()
    assert duplicate.duplicate_of_id == representative.id
    assert count(session, Item) == count(session, ExtractionResult) == 2
    decision = session.scalars(
        select(DuplicateDecision).where(DuplicateDecision.item_id == duplicate.id)
    ).one()
    assert decision.decision == "duplicate" and decision.score == 1
    collect(session, body.replace(b"gateway", b"sensor"))
    process_phase2(session)
    session.commit()
    assert representative.version == 2
    assert duplicate.duplicate_of_id is None and duplicate.status == ItemStatus.REVIEW_PENDING
    assert count(session, ExtractionResult) == 3


def test_stale_acquisition_message_does_not_overwrite_latest_revision(
    acquisition_session: Session,
) -> None:
    session = acquisition_session
    collect(session)
    collect(session, RSS.replace(b"Feature one", b"Feature two"))
    assert process_phase2(session)["extraction"] == 2
    session.commit()
    result = session.scalars(select(ExtractionResult)).one()
    assert result.revision == 2 and result.payload_json["body"] == "Feature two"


def test_tampered_outbox_payload_rolls_back_processing(acquisition_session: Session) -> None:
    session = acquisition_session
    collect(session)
    message = session.scalars(select(ModuleMessage)).one()
    message.payload_json = {**message.payload_json, "content_sha256": "0" * 64}
    session.commit()
    with pytest.raises(ValueError, match="OUTBOX_HASH_MISMATCH"):
        process_phase2(session)
    session.rollback()
    assert count(session, ExtractionResult) == 0
    assert message.status == "pending"
