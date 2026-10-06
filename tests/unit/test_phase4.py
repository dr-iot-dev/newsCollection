import copy
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import create_user
from app.contracts.wordpress_v1 import (
    PublishApprovalRequestV1,
    PublishRequestV1,
    WordPressRequestV1,
)
from app.core.config import get_settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    AuditEvent,
    Item,
    ItemStatus,
    LegalStatus,
    Publication,
    Review,
    Source,
)
from app.infrastructure.db.session import get_db
from app.infrastructure.wordpress import WordPressClient, validate_base_url
from app.main import create_app
from app.modules.publication.service import normalize_source_section, sanitize_html
from app.orchestration.publication import PublicationService
from tests.unit.test_phase3 import prepared, review_request, settings


class CMS:
    def __init__(self):
        self.posts = {}
        self.requests = []
        self.create_fault = None
        self.publish_fault = None

    def handler(self, request):
        self.requests.append(request)
        data = json.loads(request.content) if request.content else None
        post_id = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            if post_id == "posts":
                found = [p for p in self.posts.values() if p["slug"] == request.url.params["slug"]]
                return httpx.Response(200, json=found)
            return httpx.Response(200, json=self.posts[int(post_id)])
        if post_id == "posts":
            if self.create_fault == "before":
                raise httpx.ReadTimeout("fixture-secret", request=request)
            remote_id = len(self.posts) + 1
            post = {
                **data,
                "id": remote_id,
                "type": "post",
                "link": f"https://cms.example/?p={remote_id}",
                "modified_gmt": "2026-10-01T01:00:00",
                **{k: {"raw": data[k]} for k in ("title", "content", "excerpt")},
            }
            self.posts[remote_id] = post
            if self.create_fault == "after":
                raise httpx.ReadTimeout("fixture-secret", request=request)
            return httpx.Response(201, json=post)
        if self.publish_fault == "before":
            return httpx.Response(503, json={"secret": "never-logged"})
        post = self.posts[int(post_id)]
        post.update(data)
        post["modified_gmt"] = "2026-10-01T01:01:00"
        if self.publish_fault == "after":
            raise httpx.ReadTimeout("fixture-secret", request=request)
        return httpx.Response(200, json=post)

    def client(self):
        return WordPressClient(
            "https://cms.example",
            "dedicated-user",
            "fixture-password",
            transport=httpx.MockTransport(self.handler),
            sleep=lambda _: None,
        )

    @property
    def writes(self):
        return [r for r in self.requests if r.method == "POST"]


def setup_publication(session):
    author, _ = create_user(session, "author", ["editor"])
    reviewer, _ = create_user(session, "reviewer", ["reviewer"])
    publisher, _ = create_user(session, "publisher", ["publisher"])
    session.commit()
    item, editorial, _ = prepared(session, author.id)
    draft = editorial.draft(item.id)
    editorial.verify(draft.id)
    editorial.review(item.id, review_request(item, draft), reviewer.id)
    session.commit()
    config = settings().model_copy(
        update={
            "wordpress_enabled": True,
            "wordpress_base_url": "https://cms.example",
            "wordpress_category_map": {"iot_platform": 12},
        }
    )
    cms = CMS()
    svc = PublicationService(session, config, cms.client())
    return item, draft, author, reviewer, publisher, config, cms, svc


def request(item, draft):
    return WordPressRequestV1(expected_version=item.workflow_version, draft_id=draft.id)


def approval_request(item, draft, row, confirm=True):
    return PublishApprovalRequestV1(
        **request(item, draft).model_dump(),
        publication_id=row.id,
        confirm_publish=confirm,
    )


def publish_request(item, draft, row, approval):
    return PublishRequestV1(
        **request(item, draft).model_dump(),
        publication_id=row.id,
        publish_approval_id=approval.id,
    )


def test_two_human_approvals_publish_and_replay_are_audited(acquisition_session):
    session = acquisition_session
    item, draft, author, _, publisher, _, cms, svc = setup_publication(session)
    row = svc.create_draft(item.id, request(item, draft), author.id)
    assert row.state == "drafted" and item.status == ItemStatus.WP_DRAFTED
    assert cms.writes[0].url.path == "/wp-json/wp/v2/posts"
    sent = json.loads(cms.writes[0].content)
    assert sent["status"] == "draft" and sent["categories"] == [12]
    assert sent["content"].count("<h2>出典</h2>") == 1
    assert sent["content"].count('href="https://vendor.example/news/one"') == 1
    assert svc.create_draft(item.id, request(item, draft), author.id).id == row.id
    assert len(cms.writes) == 1
    with pytest.raises(EditorialError, match="ROLE_REQUIRED"):
        svc.approve_publish(item.id, approval_request(item, draft, row), author.id)
    with pytest.raises(EditorialError, match="CONFIRMATION_REQUIRED"):
        svc.approve_publish(item.id, approval_request(item, draft, row, False), publisher.id)
    with pytest.raises(EditorialError, match="PUBLISH_APPROVAL_REQUIRED"):
        svc.publish(
            item.id,
            PublishRequestV1(
                **request(item, draft).model_dump(),
                publication_id=row.id,
                publish_approval_id=uuid4(),
            ),
            publisher.id,
        )
    assert len(cms.writes) == 1
    approval = svc.approve_publish(item.id, approval_request(item, draft, row), publisher.id)
    assert item.status == ItemStatus.PUBLISH_APPROVED
    assert svc.approve_publish(item.id, approval_request(item, draft, row), publisher.id).id == (
        approval.id
    )
    row = svc.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
    assert item.status == ItemStatus.PUBLISHED and row.remote_status == "publish"
    assert row.remote_post_id == "1" and row.remote_url == "https://cms.example/?p=1"
    assert row.published_at is not None and len(cms.posts) == 1 and len(cms.writes) == 2
    assert json.loads(cms.writes[-1].content) == {"status": "publish"}
    assert (
        svc.publish(item.id, publish_request(item, draft, row, approval), publisher.id).id == row.id
    )
    assert len(cms.writes) == 2
    actions = {a.action for a in session.scalars(select(AuditEvent))}
    assert {
        "wordpress.create_intent",
        "wordpress.drafted",
        "wordpress.publish_approved",
        "wordpress.publish_intent",
        "wordpress.published",
    } <= actions
    assert cms.writes[0].headers["Authorization"].startswith("Basic ")


@pytest.mark.parametrize("fault", ["before", "after"])
def test_create_timeout_is_durable_and_never_reposts(acquisition_session, fault):
    session = acquisition_session
    item, draft, author, _, _, config, cms, svc = setup_publication(session)
    cms.create_fault = fault
    with pytest.raises(EditorialError, match="NETWORK_UNCERTAIN"):
        svc.create_draft(item.id, request(item, draft), author.id)
    row = session.scalars(select(Publication)).one()
    assert row.state == "creating" and item.status == ItemStatus.APPROVED
    item_id, draft_id, author_id, row_id = item.id, draft.id, author.id, row.id
    # A new session demonstrates that the sending intent survived the failed API call.
    with Session(session.get_bind(), expire_on_commit=False) as recovered:
        new_item = recovered.get(Item, item_id)
        req = WordPressRequestV1(expected_version=new_item.workflow_version, draft_id=draft_id)
        service = PublicationService(recovered, config, cms.client())
        if fault == "after":
            row = service.create_draft(item_id, req, author_id)
            assert row.remote_post_id == "1" and new_item.status == ItemStatus.WP_DRAFTED
        else:
            for _ in range(3):
                with pytest.raises(EditorialError, match="RECONCILIATION_PENDING"):
                    service.reconcile(row_id)
            assert new_item.status == ItemStatus.APPROVED
    assert len(cms.writes) == 1 and len(cms.posts) == (1 if fault == "after" else 0)


@pytest.mark.parametrize("fault", ["before", "after"])
def test_publish_failure_and_timeout_reconcile_without_new_posts(acquisition_session, fault):
    session = acquisition_session
    item, draft, author, _, publisher, _, cms, svc = setup_publication(session)
    row = svc.create_draft(item.id, request(item, draft), author.id)
    approval = svc.approve_publish(item.id, approval_request(item, draft, row), publisher.id)
    cms.publish_fault = fault
    with pytest.raises(EditorialError):
        svc.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
    assert item.status == ItemStatus.PUBLISH_APPROVED
    if fault == "after":
        svc.reconcile(row.id)
        assert item.status == ItemStatus.PUBLISHED
        assert len(cms.writes) == 2
    else:
        svc.reconcile(row.id)
        assert item.status == ItemStatus.PUBLISH_APPROVED
        cms.publish_fault = None
        svc.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
        assert item.status == ItemStatus.PUBLISHED
    assert len(cms.posts) == 1


@pytest.mark.parametrize(
    "change",
    [
        "content",
        "title",
        "tags",
        "categories",
        "modified_gmt",
        "slug",
        "status",
    ],
)
def test_remote_edits_block_publish_and_never_overwrite(acquisition_session, change):
    session = acquisition_session
    item, draft, author, _, publisher, _, cms, svc = setup_publication(session)
    row = svc.create_draft(item.id, request(item, draft), author.id)
    approval = svc.approve_publish(item.id, approval_request(item, draft, row), publisher.id)
    cms.posts[1][change] = (
        {"raw": "Human edit"}
        if change in {"content", "title"}
        else [999]
        if change in {"tags", "categories"}
        else "publish"
        if change == "status"
        else "changed"
    )
    before = copy.deepcopy(cms.posts)
    with pytest.raises(EditorialError, match="REMOTE_CONFLICT"):
        svc.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
    assert cms.posts == before and len(cms.writes) == 1
    assert item.status == ItemStatus.PUBLISH_APPROVED


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "item_version",
        "model",
        "mapping",
        "review",
        "draft_body",
        "publisher_revoked",
        "reviewer_revoked",
        "duplicate",
    ],
)
def test_stale_or_revoked_approvals_block_publish_before_http(acquisition_session, change):
    session = acquisition_session
    item, draft, author, reviewer, publisher, config, cms, svc = setup_publication(session)
    row = svc.create_draft(item.id, request(item, draft), author.id)
    approval = svc.approve_publish(item.id, approval_request(item, draft, row), publisher.id)
    if change == "source":
        session.get(Source, item.source_id).legal_status = LegalStatus.PENDING
    elif change == "item_version":
        item.version += 1
    elif change == "model":
        config = config.model_copy(update={"ai_verifier_model": "changed"})
        svc = PublicationService(session, config, cms.client())
    elif change == "mapping":
        config = config.model_copy(update={"wordpress_category_map": {"iot_platform": 99}})
        svc = PublicationService(session, config, cms.client())
    elif change == "review":
        session.add(
            Review(
                item_id=item.id,
                draft_id=draft.id,
                reviewer_id=reviewer.id,
                decision="needs_changes",
                checklist_json={},
                comment="Reconsidered",
            )
        )
    elif change == "draft_body":
        draft.body_markdown += "\nHuman edit"
    elif change == "publisher_revoked":
        publisher.active = False
    elif change == "reviewer_revoked":
        reviewer.active = False
    else:
        item.duplicate_of_id = item.id
    session.commit()
    before = len(cms.requests)
    with pytest.raises(EditorialError):
        svc.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
    assert len(cms.requests) == before and len(cms.writes) == 1


def test_human_review_missing_and_four_eyes_block_all_sends(acquisition_session):
    session = acquisition_session
    item, draft, author, _, _publisher, _, cms, svc = setup_publication(session)
    author.roles = ["editor", "publisher"]
    session.commit()
    row = svc.create_draft(item.id, request(item, draft), author.id)
    with pytest.raises(EditorialError, match="FOUR_EYES"):
        svc.approve_publish(item.id, approval_request(item, draft, row), author.id)
    assert len(cms.writes) == 1
    item.status = ItemStatus.REVIEW_PENDING
    session.commit()
    with pytest.raises(EditorialError, match="DRAFT_STATE_INVALID"):
        svc.create_draft(item.id, request(item, draft), author.id)
    assert len(cms.writes) == 1


def test_authenticated_api_rbac_and_disabled_default(acquisition_session):
    session = acquisition_session
    item, draft, _author, _, _publisher, config, cms, _ = setup_publication(session)
    _reader, token = create_user(session, "reader", ["viewer"])
    _editor, etoken = create_user(session, "api-editor", ["editor"])
    _pub, ptoken = create_user(session, "api-publisher", ["publisher"])
    session.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_settings] = lambda: config
    # Patch the service factory, retaining its real gate and HTTP adapter behavior.
    from unittest.mock import patch

    url = f"/api/v1/items/{item.id}/wordpress/draft"
    with (
        TestClient(app) as client,
        patch(
            "app.api.routes.publications.PublicationService",
            side_effect=lambda sess, cfg: PublicationService(sess, config, cms.client()),
        ),
    ):
        assert (
            client.post(url, json=request(item, draft).model_dump(mode="json")).status_code == 401
        )
        headers = {"Authorization": "Bearer " + token}
        assert (
            client.post(
                url, headers=headers, json=request(item, draft).model_dump(mode="json")
            ).status_code
            == 403
        )
        headers = {"Authorization": "Bearer " + etoken}
        result = client.post(
            url, headers=headers, json=request(item, draft).model_dump(mode="json")
        )
        assert result.status_code == 201
        row = session.get(Publication, UUID(result.json()["publication_id"]))
        purl = f"/api/v1/items/{item.id}/wordpress/publish-approval"
        assert (
            client.post(
                purl,
                headers=headers,
                json=approval_request(item, draft, row).model_dump(mode="json"),
            ).status_code
            == 403
        )
        headers = {"Authorization": "Bearer " + ptoken}
        assert (
            client.post(
                purl,
                headers=headers,
                json=approval_request(item, draft, row).model_dump(mode="json"),
            ).status_code
            == 201
        )
        headers = {"Authorization": "Bearer " + token}
        response = client.get(f"/api/v1/items/{item.id}/publications", headers=headers)
        assert response.status_code == 200
        assert "password" not in response.text and "package_json" not in response.text
    with pytest.raises(EditorialError, match="WORDPRESS_DISABLED"):
        PublicationService(session, settings(), cms.client())


@pytest.mark.parametrize(
    "url",
    [
        "http://cms.example",
        "https://user:password@cms.example",
        "https://cms.example/?token=secret",
        "https://localhost",
        "https://127.0.0.1",
        "https://cms.example:8443",
        "https://cms.example/../admin",
    ],
)
def test_wordpress_https_origin_validation(url):
    with pytest.raises(EditorialError):
        validate_base_url(url)


def test_sanitizer_removes_active_content_media_and_unsafe_links():
    value = sanitize_html(
        '<p onclick="evil()" style="bad">Safe<strong>bold</strong></p>'
        '<script>secret()</script><iframe src="https://evil.example"></iframe>'
        '<svg><script>x</script></svg><img src="https://evil.example/pixel">'
        '<a href="javascript:evil()" onmouseover="bad">bad link</a>'
        '<a href="https://vendor.example/source" target="_blank">Source</a>'
        "<!-- secret -->"
    )
    assert "secret" not in value and "evil" not in value and "style=" not in value
    assert "<img" not in value and "onclick" not in value and "onmouseover" not in value
    assert "<a>bad link</a>" in value
    assert 'href="https://vendor.example/source"' in value and "noopener noreferrer" in value
    assert "<strong>bold</strong>" in value


def test_response_errors_redirects_and_retry_do_not_leak_credentials():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://attacker.example/"})

    port = WordPressClient(
        "https://cms.example", "user", "password", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(EditorialError) as exc:
        port.find("news-test")
    assert len(requests) == 1 and "password" not in str(exc.value)
    for method, attempts in [("GET", 3), ("POST", 1)]:
        requests.clear()

        def unavailable(request):
            requests.append(request)
            return httpx.Response(503, headers={"Retry-After": "0"}, json={"secret": "bad"})

        port = WordPressClient(
            "https://cms.example",
            "user",
            "password",
            transport=httpx.MockTransport(unavailable),
            sleep=lambda _: None,
        )
        with pytest.raises(EditorialError, match="REMOTE_UNAVAILABLE"):
            port.request(method, "")
        assert len(requests) == attempts


def test_mapping_ids_and_publish_confirmation_are_strict():
    with pytest.raises(ValidationError):
        PublishApprovalRequestV1(
            expected_version=1, draft_id=uuid4(), publication_id=uuid4(), confirm_publish="true"
        )
    with pytest.raises(ValidationError):
        settings().__class__(wordpress_category_map={"iot_platform": 0})


def test_concurrent_create_requests_do_not_duplicate_on_postgresql(acquisition_session):
    session = acquisition_session
    if session.get_bind().dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency is exercised on PostgreSQL")
    item, draft, author, _, _, config, cms, _ = setup_publication(session)
    req = request(item, draft)
    item_id, author_id, engine = item.id, author.id, session.get_bind()

    def run():
        with Session(engine, expire_on_commit=False) as other:
            try:
                return (
                    PublicationService(other, config, cms.client())
                    .create_draft(item_id, req, author_id)
                    .id
                )
            except EditorialError as exc:
                return exc.code

    session.commit()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: run(), range(2)))
    assert len(cms.writes) == 1 and len(cms.posts) == 1
    assert "VERSION_CONFLICT" in results or "WORDPRESS_RECONCILIATION_PENDING" in results


def test_unapproved_item_cannot_create_a_wordpress_draft(acquisition_session):
    session = acquisition_session
    item, draft, author, reviewer, _, _, cms, svc = setup_publication(session)
    session.add(
        Review(
            item_id=item.id,
            draft_id=draft.id,
            reviewer_id=reviewer.id,
            decision="needs_changes",
            checklist_json={},
            comment="Not approved",
        )
    )
    session.commit()
    # Even a mismatched APPROVED status cannot bypass the actual human review record.
    assert item.status == ItemStatus.APPROVED
    with pytest.raises(EditorialError, match="HUMAN_APPROVAL_REQUIRED"):
        svc.create_draft(item.id, request(item, draft), author.id)
    assert cms.requests == []


def test_same_wordpress_origin_has_the_same_target_identity():
    assert validate_base_url("https://CMS.example:443/subdir/") == "https://cms.example/subdir"
    assert validate_base_url("https://cms.example/subdir") == "https://cms.example/subdir"


def test_invalid_wordpress_responses_are_rejected():
    base = {
        "id": 1,
        "type": "post",
        "link": "https://cms.example/?p=1",
        "status": "draft",
        "slug": "news-test",
        "modified_gmt": "2026-10-01T01:00:00",
        "title": {"raw": "title"},
        "content": {"raw": "content"},
        "excerpt": {"raw": ""},
        "categories": [12],
        "tags": [],
    }
    for key, value in [
        ("content", {"rendered": "not raw"}),
        ("id", True),
        ("categories", [True]),
        ("status", "unknown"),
        ("link", "https://attacker.example/"),
        ("modified_gmt", None),
    ]:
        port = WordPressClient(
            "https://cms.example",
            "user",
            "password",
            transport=httpx.MockTransport(
                lambda _, k=key, v=value: httpx.Response(
                    200,
                    json={**base, k: v},
                )
            ),
        )
        with pytest.raises(EditorialError):
            port.get("1")


def test_wordpress_response_body_is_bounded():
    port = WordPressClient(
        "https://cms.example",
        "user",
        "password",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 1000001)),
    )
    with pytest.raises(EditorialError, match="RESPONSE_TOO_LARGE"):
        port.get("1")


def test_existing_publication_upgrade_is_preserved_and_requires_review(acquisition_session):
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    from app.infrastructure.db.models import Base

    session = acquisition_session
    item, draft, author, _, _, _, cms, svc = setup_publication(session)
    row = svc.create_draft(item.id, request(item, draft), author.id)
    row_id = row.id
    engine = session.get_bind()
    session.commit()
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        # The fixture schema already equals head; exercise a real previous-version row.
        command.stamp(config, "head")
        command.downgrade(config, "20261001_0003")
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    session.expire_all()
    row = session.get(Publication, row_id)
    assert row.remote_post_id == "1" and row.state == "legacy"
    assert row.package_json is None and row.payload_json is None
    before = len(cms.requests)
    with pytest.raises(EditorialError, match="LEGACY_REVIEW_REQUIRED"):
        svc.create_draft(item.id, request(item, draft), author.id)
    assert len(cms.requests) == before


def test_dns_pinning_blocks_rebinding_without_sending_credentials(monkeypatch):
    from app.infrastructure.wordpress import WordPressTransport

    calls = []
    transport = WordPressTransport("cms.example")
    transport.inner.close()
    transport.inner = httpx.MockTransport(
        lambda req: calls.append(req) or httpx.Response(200, json=[])
    )
    monkeypatch.setattr(
        "app.infrastructure.wordpress.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    port = WordPressClient("https://cms.example", "user", "password", transport=transport)
    assert port.find("news-test") is None
    assert calls[0].url.host == "93.184.216.34"
    assert calls[0].headers["Host"] == "cms.example"
    assert calls[0].extensions["sni_hostname"] == "cms.example"
    monkeypatch.setattr(
        "app.infrastructure.wordpress.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(EditorialError, match="DNS_BLOCKED"):
        port.find("news-test")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "content",
    [
        "<p>Article.</p>",
        "<p>Article.</p>\n<h2>出典</h2><ul><li>https://old.example/source</li></ul>",
        "<p>Article.</p>\n<h2>出典</h2><ul><li>https://vendor.example/source</li></ul>"
        '<h2>出典</h2><ul><li><a href="https://vendor.example/source">Source</a></li></ul>',
    ],
)
def test_source_section_is_single_linked_and_idempotent(content):
    urls = [
        "https://vendor.example/source",
        "https://other.example/source",
        "https://vendor.example/source",
    ]
    normalized = normalize_source_section(content, urls)
    assert normalized.count("<h2>出典</h2>") == 1
    assert normalized.count('href="https://vendor.example/source"') == 1
    assert normalized.count('href="https://other.example/source"') == 1
    assert "old.example" not in normalized
    assert "<p>Article.</p>" in normalized
    assert normalize_source_section(normalized, urls) == normalized


def test_source_normalization_preserves_article_sections_and_quoted_headings():
    value = (
        "<p>出典に基づく本文。</p>"
        "<pre><code>## 出典</code></pre>"
        "<blockquote><h2>出典</h2><p>Quoted heading.</p></blockquote>"
        "<h2><em>出典</em></h2><ul><li>Old source.</li></ul>"
        "<h3>Old source details</h3><p>Only part of old sources.</p>"
        "<h2>Article limitations</h2><p>Keep this article section.</p>"
    )
    normalized = normalize_source_section(value, ["https://vendor.example/source"])
    assert "<p>出典に基づく本文。</p>" in normalized
    assert "<pre><code>## 出典</code></pre>" in normalized
    assert "<blockquote><h2>出典</h2><p>Quoted heading.</p></blockquote>" in normalized
    assert "Old source" not in normalized and "Only part" not in normalized
    assert "<h2>Article limitations</h2><p>Keep this article section.</p>" in normalized
    assert normalized.endswith("</a></li></ul>")


@pytest.mark.parametrize(
    "urls", [[], ["http://vendor.example/source"], ["https://user:secret@vendor.example/source"]]
)
def test_source_normalization_requires_verified_safe_source_links(urls):
    with pytest.raises(EditorialError, match="WORDPRESS_SOURCE_LINK_REQUIRED"):
        normalize_source_section("<p>Article.</p>", urls)
