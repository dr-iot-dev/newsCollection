import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.wordpress_v1 import PublishApprovalRequestV1, WordPressRequestV1
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import ItemStatus, Publication, Review
from app.orchestration.publication import PublicationService, process_verified_publications
from app.orchestration.research import prepare_comparison
from tests.unit.test_comparison_research import (
    add_article,
    prepared_root,
    seed_articles,
)
from tests.unit.test_phase3 import settings
from tests.unit.test_phase4 import CMS


def config(**updates):
    return settings().model_copy(update={
        "comparison_min_sources": 3,
        "review_required": False,
        "research_refresh_sources": False,
        "wordpress_enabled": True,
        "wordpress_base_url": "https://cms.example",
        "wordpress_category_map": {"edge_ai": 12},
        **updates,
    })


def prepared(session, **updates):
    target, _previous, _competitor = seed_articles(session)
    service = prepared_root(session, target, config(**updates))
    research = prepare_comparison(service, target.id)
    package = service.comparison(
        target.id, research.previous_ids, research.competitor_ids, request_missing=False
    )
    return target, service, package


def test_defaults_and_invalid_minimum(monkeypatch):
    monkeypatch.delenv("COMPARISON_MIN_SOURCES", raising=False)
    monkeypatch.delenv("REVIEW_REQUIRED", raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.comparison_min_sources == 3
    assert defaults.review_required is False
    for value in (0, 22):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, comparison_min_sources=value)


def test_two_sources_block_generation_and_cannot_count_duplicate_urls(acquisition_session):
    session = acquisition_session
    target, _previous, competitor = seed_articles(session)
    service = prepared_root(session, target, config())
    service.facts(competitor.id)
    package = service.comparison(target.id, competitor_ids=(competitor.id,), request_missing=False)
    with pytest.raises(EditorialError, match="COMPARISON_MIN_SOURCES_REQUIRED"):
        service.draft(target.id)
    assert not service.runner.provider.calls
    dto = ArticlePackageV1.model_validate(package.payload_json)
    same = dto.source_references[-1].model_copy(update={
        "url": str(dto.source_references[-1].url) + "?utm_source=duplicate#section"
    })
    with pytest.raises(EditorialError, match="COMPARISON_MIN_SOURCES_REQUIRED"):
        service.validate_source_count(dto.model_copy(update={
            "source_references": (*dto.source_references, same)
        }))
    service.settings = config(comparison_min_sources=2)
    assert service.draft(target.id) is not None


def test_multiple_competitors_meet_minimum_without_previous_article(acquisition_session):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    first = add_article(session, "competitor", "OtherCorp", "XYZ200", 16, "29,800", 30)
    second = add_article(session, "alternative", "ThirdCorp", "DEF300", 32, "39,800", 29)
    service = prepared_root(session, target, config())
    research = prepare_comparison(service, target.id)
    assert not research.previous_ids
    assert set(research.competitor_ids) == {first.id, second.id}
    package = service.comparison(
        target.id, research.previous_ids, research.competitor_ids, request_missing=False
    )
    assert len(package.payload_json["source_references"]) == 3
    draft = service.draft(target.id)
    assert draft is not None
    assert service.verify(draft.id).overall_result == "pass"


def test_verified_three_source_draft_is_automatically_sent_once(acquisition_session):
    session = acquisition_session
    item, service, _package = prepared(session)
    draft = service.draft(item.id)
    verification = service.verify(draft.id)
    assert verification.overall_result == "pass"
    assert item.status == ItemStatus.VERIFIED
    session.commit()
    cms = CMS()
    assert process_verified_publications(session, service.settings, port=cms.client()) == 1
    assert item.status == ItemStatus.WP_DRAFTED
    assert len(cms.writes) == 1
    assert next(iter(cms.posts.values()))["status"] == "draft"
    assert session.scalars(select(Review)).all() == []
    row = session.scalars(select(Publication)).one()
    assert row.package_json["producer"] == "verification"
    assert row.package_json["payload"]["approval_id"] == str(verification.id)
    assert process_verified_publications(session, service.settings, port=cms.client()) == 0
    assert len(cms.writes) == 1


def test_required_review_and_disabled_wordpress_prevent_automatic_send(acquisition_session):
    session = acquisition_session
    item, service, _ = prepared(session, review_required=True)
    draft = service.draft(item.id)
    assert service.verify(draft.id).overall_result == "pass"
    assert item.status == ItemStatus.REVIEW_PENDING
    session.commit()
    cms = CMS()
    assert process_verified_publications(session, service.settings, port=cms.client()) == 0
    disabled = config(wordpress_enabled=False)
    assert process_verified_publications(session, disabled, port=cms.client()) == 0
    with pytest.raises(EditorialError, match="HUMAN_APPROVAL_REQUIRED"):
        PublicationService(session, service.settings, cms.client()).create_draft(
            item.id, WordPressRequestV1(expected_version=item.workflow_version, draft_id=draft.id)
        )
    assert not cms.writes


@pytest.mark.parametrize("change", ["verification", "minimum", "content"])
def test_latest_validation_is_rechecked_before_send(acquisition_session, change):
    session = acquisition_session
    item, service, _ = prepared(session)
    draft = service.draft(item.id)
    verification = service.verify(draft.id)
    assert verification.overall_result == "pass"
    cfg = service.settings
    if change == "verification":
        verification.overall_result = "fail"
    elif change == "minimum":
        cfg = config(comparison_min_sources=4)
    else:
        draft.title = "Changed after verification"
    session.commit()
    cms = CMS()
    assert process_verified_publications(session, cfg, port=cms.client()) == 0
    assert not cms.writes


def test_auto_draft_does_not_allow_publication_without_human_review(acquisition_session):
    from app.api.auth import create_user

    session = acquisition_session
    item, service, _ = prepared(session)
    draft = service.draft(item.id)
    service.verify(draft.id)
    publisher, _ = create_user(session, "publisher", ["publisher"])
    session.commit()
    cms = CMS()
    process_verified_publications(session, service.settings, port=cms.client())
    row = session.scalars(select(Publication)).one()
    with pytest.raises(EditorialError, match="HUMAN_APPROVAL_REQUIRED"):
        PublicationService(session, service.settings, cms.client()).approve_publish(
            item.id,
            PublishApprovalRequestV1(
                expected_version=item.workflow_version, draft_id=draft.id,
                publication_id=row.id, confirm_publish=True,
            ),
            publisher.id,
        )
    assert len(cms.writes) == 1


def test_ambiguous_create_is_reconciled_without_duplicate_post(acquisition_session):
    session = acquisition_session
    item, service, _ = prepared(session)
    draft = service.draft(item.id)
    service.verify(draft.id)
    session.commit()
    cms = CMS()
    cms.create_fault = "after"
    assert process_verified_publications(session, service.settings, port=cms.client()) == 0
    assert len(cms.posts) == len(cms.writes) == 1
    cms.create_fault = None
    assert process_verified_publications(session, service.settings, port=cms.client()) == 1
    assert item.status == ItemStatus.WP_DRAFTED
    assert len(cms.posts) == len(cms.writes) == 1



@pytest.mark.parametrize("require_review", [False, True])
def test_auto_draft_can_be_human_reviewed_before_explicit_publish(
    acquisition_session, require_review
):
    from app.api.auth import create_user
    from tests.unit.test_phase3 import review_request

    session = acquisition_session
    item, service, _ = prepared(session)
    draft = service.draft(item.id)
    service.verify(draft.id)
    reviewer, _ = create_user(session, "reviewer", ["reviewer"])
    publisher, _ = create_user(session, "publisher", ["publisher"])
    session.commit()
    cms = CMS()
    process_verified_publications(session, service.settings, port=cms.client())
    row = session.scalars(select(Publication)).one()
    service.review(item.id, review_request(item, draft), reviewer.id)
    assert item.status == ItemStatus.WP_DRAFTED
    session.commit()
    publishing_config = service.settings.model_copy(update={"review_required": require_review})
    approval = PublicationService(session, publishing_config, cms.client()).approve_publish(
        item.id,
        PublishApprovalRequestV1(
            expected_version=item.workflow_version, draft_id=draft.id,
            publication_id=row.id, confirm_publish=True,
        ),
        publisher.id,
    )
    assert item.status == ItemStatus.PUBLISH_APPROVED
    assert approval.review_id == session.scalars(select(Review)).one().id
    assert len(cms.writes) == 1



def test_legacy_review_pending_draft_can_be_reconciled_after_timeout(acquisition_session):
    session = acquisition_session
    item, service, _ = prepared(session)
    draft = service.draft(item.id)
    service.verify(draft.id)
    item.status = ItemStatus.REVIEW_PENDING
    session.commit()
    cms = CMS()
    cms.create_fault = "after"
    process_verified_publications(session, service.settings, port=cms.client())
    row = session.scalars(select(Publication)).one()
    cms.create_fault = None
    PublicationService(session, service.settings, cms.client()).reconcile(row.id)
    assert item.status == ItemStatus.WP_DRAFTED
    assert len(cms.writes) == 1
