import copy
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.wordpress_v1 import WordPressRequestV1
from app.core.editorial import EditorialError
from app.core.source_set import source_set_hash
from app.infrastructure.db.models import ArticleDraft, Item, Publication, SourceSetClaim
from app.orchestration.publication import PublicationService
from app.orchestration.source_sets import package_source_set
from tests.unit.test_comparison_research import add_article, prepared_root
from tests.unit.test_editorial_policy import config
from tests.unit.test_phase4 import CMS


def three_articles(session):
    articles = [
        add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30),
        add_article(session, "competitor", "OtherCorp", "XYZ200", 16, "29,800", 30),
        add_article(session, "alternative", "ThirdCorp", "DEF300", 32, "39,800", 30),
    ]
    service = prepared_root(session, articles[0], config())
    for item in articles[1:]:
        service.facts(item.id)
    service.comparison(articles[0].id, (), tuple(i.id for i in articles[1:]),
                       request_missing=False)
    return articles, service


def rotated(session, articles):
    service = prepared_root(session, articles[1], config())
    service.comparison(articles[1].id, (), (articles[2].id, articles[0].id),
                       request_missing=False)
    return service


def test_identity_ignores_order_repetitions_tracking_and_fragment():
    urls = ["https://vendor.example/a", "https://vendor.example/b"]
    assert source_set_hash(urls) == source_set_hash([
        urls[1], urls[0] + "?utm_source=feed#detail", urls[1] + "?fbclid=tracker",
    ])
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


def test_revised_draft_cannot_create_second_cms_post(acquisition_session):
    from app.contracts.editorial_v1 import WritingOutputV1
    from tests.unit.test_comparison_research import ComparisonProvider

    session = acquisition_session
    articles, service = three_articles(session)
    item = articles[0]
    first = service.draft(item.id)
    service.verify(first.id)
    session.commit()
    cms = CMS()
    publisher = PublicationService(session, service.settings, cms.client())
    row = publisher.create_draft(item.id, WordPressRequestV1(
        expected_version=item.workflow_version, draft_id=first.id,
    ))
    output = WritingOutputV1.model_validate(ComparisonProvider().generate(
        model="writer-test", data=service.package(item)[1].model_dump(mode="json"),
        instructions="", schema={}, max_output_tokens=4000,
    ).output)
    revised = service.draft(item.id, manual=output)
    assert revised.revision == first.revision + 1
    service.verify(revised.id)
    session.commit()
    with pytest.raises(EditorialError, match="WORDPRESS_SOURCE_SET_DUPLICATE"):
        publisher.create_draft(item.id, WordPressRequestV1(
            expected_version=item.workflow_version, draft_id=revised.id,
        ))
    assert len(cms.writes) == len(cms.posts) == 1
    assert session.scalars(select(Publication)).all() == [row]


class TrashCMS(CMS):
    trash_fault = False

    def handler(self, request):
        if request.method != "DELETE":
            return super().handler(request)
        self.requests.append(request)
        assert request.url.params["force"] == "false"
        post = self.posts[int(request.url.path.rsplit("/", 1)[-1])]
        post["status"] = "trash"
        post["modified_gmt"] = "2026-10-06T01:01:00"
        if self.trash_fault:
            raise httpx.ReadTimeout("fixture", request=request)
        return httpx.Response(200, json=post)


def old_duplicates(session):
    """Seed records produced before source-set ownership existed."""
    articles, service = three_articles(session)
    cms = TrashCMS()
    first = service.draft(articles[0].id)
    service.verify(first.id)
    session.commit()
    publisher = PublicationService(session, service.settings, cms.client())
    keep = publisher.create_draft(articles[0].id, WordPressRequestV1(
        expected_version=articles[0].workflow_version, draft_id=first.id,
    ))
    for claim in session.scalars(select(SourceSetClaim)):
        session.delete(claim)
    session.commit()
    other = rotated(session, articles)
    second = other.draft(articles[1].id)
    other.verify(second.id)
    session.commit()
    duplicate = publisher.create_draft(articles[1].id, WordPressRequestV1(
        expected_version=articles[1].workflow_version, draft_id=second.id,
    ))
    # Equivalent to backfill selecting the first sent post as retained ownership.
    for claim in session.scalars(select(SourceSetClaim)):
        claim.item_id, claim.draft_id = keep.item_id, keep.draft_id
        if claim.scope != "writing":
            claim.publication_id = keep.id
    session.commit()
    return articles, keep, duplicate, publisher, cms


def test_legacy_rotated_article_is_blocked_at_send(acquisition_session):
    session = acquisition_session
    articles, keep, duplicate, publisher, cms = old_duplicates(session)
    before = len(cms.requests)
    with pytest.raises(EditorialError, match="WORDPRESS_SOURCE_SET_DUPLICATE"):
        publisher.create_draft(articles[1].id, WordPressRequestV1(
            expected_version=articles[1].workflow_version, draft_id=duplicate.draft_id,
        ))
    assert len(cms.requests) == before
    assert session.get(SourceSetClaim, session.scalars(select(SourceSetClaim).where(
        SourceSetClaim.scope == publisher.target,
    )).one().id).publication_id == keep.id


@pytest.mark.parametrize("timeout", [False, True])
def test_duplicate_cleanup_and_timeout_reconciliation_do_not_recreate(
    acquisition_session, timeout
):
    session = acquisition_session
    _articles, keep, duplicate, publisher, cms = old_duplicates(session)
    retained = copy.deepcopy(cms.posts[int(keep.remote_post_id)])
    cms.trash_fault = timeout
    if timeout:
        with pytest.raises(EditorialError, match="WORDPRESS_NETWORK_UNCERTAIN"):
            publisher.trash_duplicate(duplicate.id, keep.id)
        assert duplicate.state == "trashing"
        publisher.reconcile(duplicate.id)
    else:
        publisher.trash_duplicate(duplicate.id, keep.id)
    assert duplicate.state == "trashed" and duplicate.remote_status == "trash"
    assert cms.posts[int(keep.remote_post_id)] == retained
    publisher.reconcile(duplicate.id)
    publisher.trash_duplicate(duplicate.id, keep.id)
    assert len([r for r in cms.requests if r.method == "DELETE"]) == 1
    assert len(cms.posts) == 2
    assert cms.posts[int(duplicate.remote_post_id)]["status"] == "trash"


@pytest.mark.parametrize("change", ["published", "edited", "different_sources"])
def test_cleanup_preserves_published_or_edited_or_unrelated_posts(acquisition_session, change):
    from app.contracts.envelope import canonical_payload_hash
    from app.infrastructure.db.models import ArticlePackage

    session = acquisition_session
    _articles, keep, duplicate, publisher, cms = old_duplicates(session)
    if change == "published":
        cms.posts[int(duplicate.remote_post_id)]["status"] = "publish"
    elif change == "edited":
        cms.posts[int(duplicate.remote_post_id)]["title"]["raw"] = "Human changes"
    else:
        draft = session.get(ArticleDraft, duplicate.draft_id)
        package = session.get(ArticlePackage, draft.article_package_id)
        data = copy.deepcopy(package.payload_json)
        data["source_references"] = data["source_references"][:-1]
        package.payload_json, package.payload_hash = data, canonical_payload_hash(data)
    session.commit()
    before = copy.deepcopy(cms.posts)
    with pytest.raises(EditorialError):
        publisher.trash_duplicate(duplicate.id, keep.id)
    assert cms.posts == before
    assert not any(r.method == "DELETE" for r in cms.requests)


def test_backfill_prefers_first_sent_post_and_preserves_duplicate_history(acquisition_session):
    from alembic import command
    from alembic.config import Config

    session = acquisition_session
    _articles, keep, duplicate, publisher, _cms = old_duplicates(session)
    session.commit()
    engine = session.get_bind()
    cfg = Config("alembic.ini")
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.stamp(cfg, "head")
        command.downgrade(cfg, "20261002_0006")
        command.upgrade(cfg, "head")
    session.expire_all()
    claims = session.scalars(select(SourceSetClaim)).all()
    assert len(claims) == 2
    assert {c.draft_id for c in claims} == {keep.draft_id}
    assert next(c for c in claims if c.scope == publisher.target).publication_id == keep.id
    assert session.get(Publication, duplicate.id).state == "drafted"


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


def test_concurrent_rotated_sends_create_one_cms_post(acquisition_session):
    session = acquisition_session
    if session.get_bind().dialect.name != "postgresql":
        pytest.skip("Cross-item CMS concurrency is exercised on PostgreSQL")
    articles, service = three_articles(session)
    first = service.draft(articles[0].id)
    service.verify(first.id)
    for claim in session.scalars(select(SourceSetClaim)):
        session.delete(claim)
    session.commit()
    other = rotated(session, articles)
    second = other.draft(articles[1].id)
    other.verify(second.id)
    session.commit()
    engine = session.get_bind()
    cms = CMS()
    requests = [(articles[0].id, WordPressRequestV1(
        expected_version=articles[0].workflow_version, draft_id=first.id,
    )), (articles[1].id, WordPressRequestV1(
        expected_version=articles[1].workflow_version, draft_id=second.id,
    ))]

    def run(entry):
        item_id, request = entry
        with Session(engine, expire_on_commit=False) as db:
            try:
                return str(PublicationService(db, config(), cms.client()).create_draft(
                    item_id, request,
                ).id)
            except EditorialError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(run, requests))
    assert results.count("WORDPRESS_SOURCE_SET_DUPLICATE") == 1
    assert len(cms.posts) == len(cms.writes) == 1
    assert len(session.scalars(select(Publication)).all()) == 1
