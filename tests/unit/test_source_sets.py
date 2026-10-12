from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.editorial import EditorialError
from app.core.source_set import source_set_hash
from app.infrastructure.db.models import ArticleDraft, Item, SourceSetClaim
from app.orchestration.source_sets import package_source_set
from tests.unit.test_comparison_research import add_article, prepared_root
from tests.unit.test_editorial_policy import config


def three_articles(session):
    articles = [
        add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30),
        add_article(session, "competitor", "OtherCorp", "XYZ200", 16, "29,800", 30),
        add_article(session, "alternative", "ThirdCorp", "DEF300", 32, "39,800", 30),
    ]
    service = prepared_root(session, articles[0], config())
    for item in articles[1:]:
        service.facts(item.id)
    service.comparison(articles[0].id, (), tuple(i.id for i in articles[1:]), request_missing=False)
    return articles, service


def rotated(session, articles):
    service = prepared_root(session, articles[1], config())
    service.comparison(articles[1].id, (), (articles[2].id, articles[0].id), request_missing=False)
    return service


def test_identity_ignores_order_repetitions_tracking_and_fragment():
    urls = ["https://vendor.example/a", "https://vendor.example/b"]
    assert source_set_hash(urls) == source_set_hash(
        [
            urls[1],
            urls[0] + "?utm_source=feed#detail",
            urls[1] + "?fbclid=tracker",
        ]
    )
    assert source_set_hash(urls) != source_set_hash([*urls, "https://vendor.example/c"])
    assert source_set_hash(urls) != source_set_hash([urls[0], urls[1] + "?article=other"])


def test_rotated_main_and_repeat_generation_do_not_call_writer(acquisition_session):
    session = acquisition_session
    articles, service = three_articles(session)
    draft = service.draft(articles[0].id)
    session.commit()
    other = rotated(session, articles)
    for editor, item in [(service, articles[0]), (other, articles[1])]:
        calls = len(editor.runner.provider.calls)
        with pytest.raises(EditorialError, match="DRAFT_SOURCE_SET_DUPLICATE"):
            editor.draft(item.id)
        assert len(editor.runner.provider.calls) == calls
    assert session.scalars(select(ArticleDraft)).all() == [draft]
    assert package_source_set(service.package(articles[0])[1]) == package_source_set(
        other.package(articles[1])[1]
    )


def test_failed_generation_releases_claim(acquisition_session, monkeypatch):
    session = acquisition_session
    articles, service = three_articles(session)
    monkeypatch.setattr(service.runner, "run", lambda *a, **k: (None, None))
    assert service.draft(articles[0].id) is None
    session.commit()
    assert session.scalars(select(SourceSetClaim)).all() == []
    other = rotated(session, articles)
    assert other.draft(articles[1].id) is not None


def test_concurrent_rotated_generation_uses_one_reservation(acquisition_session):
    session = acquisition_session
    if session.get_bind().dialect.name != "postgresql":
        pytest.skip("Cross-item concurrency is exercised on PostgreSQL")
    articles, _service = three_articles(session)
    rotated(session, articles)
    session.commit()
    engine = session.get_bind()
    ids = [articles[0].id, articles[1].id]

    def run(item_id):
        from tests.unit.test_comparison_research import svc

        with Session(engine, expire_on_commit=False) as other:
            try:
                draft = svc(other, config()).draft(item_id)
                other.commit()
                return str(draft.id)
            except EditorialError as exc:
                other.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(run, ids))
    assert results.count("DRAFT_SOURCE_SET_DUPLICATE") == 1
    assert len(session.scalars(select(ArticleDraft)).all()) == 1
    claim = session.scalars(select(SourceSetClaim)).one()
    assert claim.item_id in ids and claim.draft_id is not None
    assert session.get(Item, claim.item_id) is not None


def test_different_source_set_can_generate_new_article(acquisition_session):
    session = acquisition_session
    articles, service = three_articles(session)
    first = service.draft(articles[0].id)
    extra = add_article(session, "extra", "FourthCorp", "GHI400", 64, "49,800", 30)
    service.facts(extra.id)
    service.comparison(articles[0].id, (), (articles[1].id, extra.id), request_missing=False)
    second = service.draft(articles[0].id)
    assert first.id != second.id
    assert len(session.scalars(select(SourceSetClaim)).all()) == 2


def test_explicit_ai_revision_preserves_claim_and_failed_history(acquisition_session):
    from app.infrastructure.db.models import ItemStatus, VerificationRun

    session = acquisition_session
    articles, service = three_articles(session)
    item = articles[0]
    first = service.draft(item.id)
    verification = service.verify(first.id)
    verification.overall_result = "fail"
    verification.blocking_issues_json = ["original_expression"]
    item.status = ItemStatus.VERIFICATION_FAILED
    session.commit()
    revised = service.draft(item.id, revise_failed=True)
    assert revised.revision == first.revision + 1
    assert revised.created_by_type == "ai" and revised.ai_run_id is not None
    claim = session.scalars(select(SourceSetClaim)).one()
    assert claim.item_id == item.id and claim.draft_id == revised.id
    assert session.get(VerificationRun, verification.id).overall_result == "fail"
    assert service.runner.provider.calls[-1][1]["revision_feedback"]["blocking_issues"] == [
        "original_expression"
    ]
    other = rotated(session, articles)
    with pytest.raises(EditorialError, match="DRAFT_SOURCE_SET_DUPLICATE"):
        other.draft(articles[1].id, revise_failed=True)


def test_ai_revision_does_not_regenerate_a_passed_draft(acquisition_session):
    session = acquisition_session
    articles, service = three_articles(session)
    first = service.draft(articles[0].id)
    service.verify(first.id)
    session.commit()
    calls = len(service.runner.provider.calls)
    with pytest.raises(EditorialError, match="DRAFT_REVISION_NOT_ALLOWED"):
        service.draft(articles[0].id, revise_failed=True)
    assert len(service.runner.provider.calls) == calls


def test_failed_ai_draft_can_use_updated_evidence_for_same_sources(acquisition_session):
    from app.infrastructure.db.models import ItemStatus
    from tests.unit.test_comparison_research import svc

    session = acquisition_session
    articles, service = three_articles(session)
    item = articles[0]
    first = service.draft(item.id)
    verification = service.verify(first.id)
    verification.overall_result = "fail"
    verification.blocking_issues_json = ["fact_support"]
    item.status = ItemStatus.VERIFICATION_FAILED
    session.commit()
    from app.ai.provider import AIResponse
    from app.modules.extraction.facts import rule_facts
    from tests.unit.test_comparison_research import ComparisonProvider
    from tests.unit.test_phase3_facts import content

    class RefreshedProvider(ComparisonProvider):
        def generate(self, **kwargs):
            if kwargs["model"] == "facts-reviewed":
                output = rule_facts(content(kwargs["data"]["body"]))
                return AIResponse(output.model_dump(mode="json"), "facts-reviewed", 10, 5, 1)
            return super().generate(**kwargs)

    refreshed = svc(
        session,
        config().model_copy(update={"ai_model_facts": "facts-reviewed"}),
        RefreshedProvider(),
    )
    for article in articles:
        refreshed.facts(article.id, mode="ai")
    refreshed.select(item.id)
    package = refreshed.comparison(
        item.id,
        (),
        (articles[1].id, articles[2].id),
        request_missing=False,
    )
    assert package.id != first.article_package_id
    revised = refreshed.draft(item.id, revise_failed=True)
    assert revised.article_package_id == package.id and revised.id != first.id
    claim = session.scalars(select(SourceSetClaim)).one()
    assert claim.draft_id == revised.id and claim.item_id == item.id
