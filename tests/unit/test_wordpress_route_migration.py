from copy import deepcopy

import pytest
from sqlalchemy import select

from app.contracts.envelope import ContractEnvelope
from app.contracts.publication_v1 import PublicationPackageV1
from app.core.editorial import EditorialError
from app.infrastructure.db.models import AuditEvent, SourceSetClaim
from app.infrastructure.wordpress import wordpress_target
from app.orchestration.publication import PublicationService
from app.orchestration.wordpress_routes import migrate_wordpress_history
from tests.unit.test_phase4 import (
    CMS,
    approval_request,
    publish_request,
    request,
    setup_publication,
)


def existing_custom(session):
    item, draft, author, _reviewer, publisher, config, _, _ = setup_publication(session)
    old_config = config.model_copy(update={
        "wordpress_post_type": "nc_news", "wordpress_rest_base": "nc-news",
    })
    cms = CMS("nc_news", "nc-news")
    old_service = PublicationService(session, old_config, cms.client())
    row = old_service.create_draft(item.id, request(item, draft), author.id)
    new_config = config.model_copy(update={
        "wordpress_post_type": "news_weave", "wordpress_rest_base": "news-weave",
    })
    new_target = wordpress_target(config.wordpress_base_url, "news_weave", "news-weave")
    return item, draft, author, publisher, old_service, row, cms, new_config, new_target


def test_migration_preserves_slug_approval_and_prevents_reposting(acquisition_session):
    session = acquisition_session
    item, draft, _author, publisher, old, row, cms, new_config, target = existing_custom(session)
    approval = old.approve_publish(item.id, approval_request(item, draft, row), publisher.id)
    payload, remote_hash = deepcopy(row.payload_json), row.remote_hash
    version = item.workflow_version
    result = migrate_wordpress_history(session, old.target, target)
    assert result["publications"] == result["source_claims"] == 1
    assert row.target == old.target and result["applied"] is False
    migrate_wordpress_history(session, old.target, target, apply=True)
    session.commit()
    assert row.payload_json == payload and row.remote_hash == remote_hash
    assert item.workflow_version == version
    envelope = ContractEnvelope[PublicationPackageV1].model_validate(row.package_json)
    assert envelope.payload.target == target
    claim = session.scalar(select(SourceSetClaim).where(SourceSetClaim.scope == target))
    assert claim.publication_id == row.id
    cms.post_type, cms.rest_base = "news_weave", "news-weave"
    cms.posts[1]["type"] = "news_weave"
    new = PublicationService(session, new_config, cms.client())
    new.validate_package(item, row)
    assert new.approved(item, draft.id)[2].slug == payload["slug"]
    before = len(cms.writes)
    new.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
    assert len(cms.writes) == before + 1
    assert len(cms.posts) == 1 and cms.posts[1]["slug"] == payload["slug"]
    assert migrate_wordpress_history(session, old.target, target, apply=True)["applied"] is False
    event = session.scalar(
        select(AuditEvent).where(AuditEvent.action == "wordpress.target_migrated")
    )
    assert event.before_json["target"] == old.target
    assert event.after_json["target"] == target


def test_migrated_draft_replay_only_reads_existing_post(acquisition_session):
    session = acquisition_session
    item, draft, author, _, old, row, cms, new_config, target = existing_custom(session)
    migrate_wordpress_history(session, old.target, target, apply=True)
    session.commit()
    cms.post_type, cms.rest_base = "news_weave", "news-weave"
    cms.posts[1]["type"] = "news_weave"
    new = PublicationService(session, new_config, cms.client())
    assert new.create_draft(item.id, request(item, draft), author.id).id == row.id
    assert len(cms.writes) == 1
    migrate_wordpress_history(session, target, old.target, apply=True)
    session.commit()
    assert row.target == old.target


def test_migration_aborts_when_destination_is_occupied(acquisition_session):
    session = acquisition_session
    _, _, _, _, old, row, _, _, target = existing_custom(session)
    original = session.scalar(select(SourceSetClaim).where(SourceSetClaim.scope == old.target))
    session.add(SourceSetClaim(scope=target, source_set_hash=original.source_set_hash,
                               item_id=original.item_id))
    session.commit()
    with pytest.raises(EditorialError, match="MIGRATION_TARGET_NOT_EMPTY"):
        migrate_wordpress_history(session, old.target, target, apply=True)
    assert row.target == old.target


def test_migration_rejects_changed_payload_before_writing(acquisition_session):
    session = acquisition_session
    _, _, _, _, old, row, _, _, target = existing_custom(session)
    row.payload_json = {**row.payload_json, "title": "Unexpected edit"}
    session.commit()
    with pytest.raises(EditorialError, match="MIGRATION_PAYLOAD_INVALID"):
        migrate_wordpress_history(session, old.target, target, apply=True)
    assert row.target == old.target
