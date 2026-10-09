import hashlib

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.wordpress import WordPressClient, wordpress_target
from app.orchestration.featured_images import FeaturedImageService, process_featured_images
from app.orchestration.publication import PublicationService
from tests.unit.test_featured_images import ImageProvider, MediaCMS
from tests.unit.test_phase4 import (
    CMS,
    approval_request,
    publish_request,
    request,
    setup_publication,
)


@pytest.fixture(params=[("nc_news", "nc-news"), ("news_weave", "news-weave")], autouse=True)
def custom_route(request, monkeypatch):
    monkeypatch.setitem(globals(), "CUSTOM_POST_TYPE", request.param[0])
    monkeypatch.setitem(globals(), "CUSTOM_REST_BASE", request.param[1])


CUSTOM_POST_TYPE = "news_weave"
CUSTOM_REST_BASE = "news-weave"


def custom_config(config):
    return config.model_copy(update={
        "wordpress_post_type": CUSTOM_POST_TYPE, "wordpress_rest_base": CUSTOM_REST_BASE,
        "featured_images_enabled": True,
    })


def test_defaults_and_target_identity_preserve_existing_posts():
    config = Settings(_env_file=None)
    assert config.wordpress_post_type == "post" and config.wordpress_rest_base is None
    legacy = "wordpress:" + hashlib.sha256(b"https://cms.example/subdir").hexdigest()
    assert wordpress_target("https://CMS.example:443/subdir/") == legacy
    assert wordpress_target("https://cms.example/subdir", "post", "posts") == legacy
    custom = wordpress_target("https://cms.example/subdir", CUSTOM_POST_TYPE, CUSTOM_REST_BASE)
    assert custom != legacy
    assert wordpress_target("https://cms.example", "news_weave", "news-weave") != (
        wordpress_target("https://cms.example", "nc_news", "nc-news")
    )
    assert custom != wordpress_target("https://cms.example/subdir", "other", CUSTOM_REST_BASE)
    assert custom != wordpress_target("https://cms.example/subdir", CUSTOM_POST_TYPE, "other")
    assert wordpress_target("https://cms.example", CUSTOM_POST_TYPE) == wordpress_target(
        "https://cms.example", CUSTOM_POST_TYPE, CUSTOM_POST_TYPE,
    )


@pytest.mark.parametrize("field,value", [
    ("wordpress_post_type", "a" * 21), ("wordpress_post_type", "../posts"),
    ("wordpress_post_type", "NC_NEWS"), ("wordpress_rest_base", "../media"),
    ("wordpress_rest_base", "nc-news?context=edit"), ("wordpress_rest_base", ""),
    ("wordpress_rest_base", "https://other.example/posts"),
])
def test_settings_reject_invalid_post_resources(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("post_type,rest_base", [
    ("../posts", None), (CUSTOM_POST_TYPE, "../media"), (CUSTOM_POST_TYPE, "nc-news/1"),
    (CUSTOM_POST_TYPE, "nc-news?foo=1"), (CUSTOM_POST_TYPE, ""),
])
def test_client_rejects_route_injection_before_requests(post_type, rest_base):
    with pytest.raises(EditorialError, match="WORDPRESS_POST_RESOURCE_INVALID"):
        WordPressClient("https://cms.example", "user", "password",
                        post_type=post_type, rest_base=rest_base)


def test_custom_client_rejects_a_regular_post_response():
    cms = CMS()
    # Create a valid regular post response with the same fields a custom post would use.
    response = {"id": 1, "type": "post", "link": "https://cms.example/?p=1",
                "status": "draft", "slug": "news-test", "modified_gmt": "2026-10-01",
                "categories": [12], "tags": [],
                **{key: {"raw": "test"} for key in ("title", "content", "excerpt")}}
    cms.posts[1] = response
    port = WordPressClient("https://cms.example", "user", "password", post_type=CUSTOM_POST_TYPE,
                           rest_base=CUSTOM_REST_BASE, transport=httpx.MockTransport(cms.handler))
    with pytest.raises(EditorialError, match="WORDPRESS_RESPONSE_INVALID"):
        port.get("1")


def test_custom_draft_publish_replay_and_legacy_history_isolation(acquisition_session):
    session = acquisition_session
    item, draft, author, _, publisher, config, _, legacy = setup_publication(session)
    config = custom_config(config)
    cms = CMS(CUSTOM_POST_TYPE, CUSTOM_REST_BASE)
    service = PublicationService(session, config, cms.client())
    row = service.create_draft(item.id, request(item, draft), author.id)
    assert row.target == service.target != legacy.target
    assert row.remote_status == "draft"
    before = len(cms.requests)
    with pytest.raises(EditorialError, match="PUBLICATION_NOT_FOUND"):
        legacy.reconcile(row.id)
    assert len(cms.requests) == before
    assert service.create_draft(item.id, request(item, draft), author.id).id == row.id
    assert len(cms.writes) == 1
    approval = service.approve_publish(
        item.id, approval_request(item, draft, row), publisher.id,
    )
    row = service.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
    assert row.remote_status == "publish" and cms.posts[1]["type"] == CUSTOM_POST_TYPE
    assert len(cms.writes) == 2
    assert {req.url.path for req in cms.requests} <= {
        f"/wp-json/wp/v2/{CUSTOM_REST_BASE}", f"/wp-json/wp/v2/{CUSTOM_REST_BASE}/1",
    }


def test_custom_create_timeout_reconciles_without_duplicate(acquisition_session):
    session = acquisition_session
    item, draft, author, _, _, config, _, _ = setup_publication(session)
    cms = CMS(CUSTOM_POST_TYPE, CUSTOM_REST_BASE)
    cms.create_fault = "after"
    service = PublicationService(session, custom_config(config), cms.client())
    with pytest.raises(EditorialError, match="NETWORK_UNCERTAIN"):
        service.create_draft(item.id, request(item, draft), author.id)
    row = service.create_draft(item.id, request(item, draft), author.id)
    assert row.remote_status == "draft" and len(cms.posts) == len(cms.writes) == 1
    assert cms.requests[-1].url.path == f"/wp-json/wp/v2/{CUSTOM_REST_BASE}"


def test_custom_featured_images_keep_media_on_its_own_route(acquisition_session):
    session = acquisition_session
    item, draft, author, _, publisher, config, _, _ = setup_publication(session)
    config = custom_config(config)
    cms = MediaCMS(CUSTOM_POST_TYPE, CUSTOM_REST_BASE)
    provider = ImageProvider()
    publication = PublicationService(session, config, cms.client())
    row = publication.create_draft(item.id, request(item, draft), author.id)
    decoration = FeaturedImageService(session, config, port=cms.client(), provider=provider)
    assert decoration.target == publication.target
    assert process_featured_images(session, config, port=cms.client(), provider=provider) == 1
    assert len(cms.uploads) == len(cms.attachments) == 1
    assert cms.uploads[0].url.path == "/wp-json/wp/v2/media"
    assert cms.attachments[0].url.path == f"/wp-json/wp/v2/{CUSTOM_REST_BASE}/1"
    approval = publication.approve_publish(
        item.id, approval_request(item, draft, row), publisher.id,
    )
    publication.publish(item.id, publish_request(item, draft, row, approval), publisher.id)
    assert cms.posts[1]["status"] == "publish" and cms.posts[1]["featured_media"] == 100


def test_clients_created_by_services_receive_post_type(acquisition_session):
    _, _, _, _, _, config, _, _ = setup_publication(acquisition_session)
    config = custom_config(config)
    config.wordpress_username = "user"
    config.wordpress_application_password = SecretStr("password")
    publication = PublicationService(acquisition_session, config)
    featured = FeaturedImageService(acquisition_session, config, provider=ImageProvider())
    for port in (publication.port, featured.port):
        assert isinstance(port, WordPressClient)
        assert port.post_type == CUSTOM_POST_TYPE and port.rest_base == CUSTOM_REST_BASE


def test_custom_trash_and_subdirectory_route():
    calls = []
    response = {"id": 1, "type": CUSTOM_POST_TYPE, "link": "https://cms.example/subdir/?p=1",
                "status": "trash", "slug": "news-test", "modified_gmt": "2026-10-01",
                "categories": [12], "tags": [],
                **{key: {"raw": "test"} for key in ("title", "content", "excerpt")}}
    port = WordPressClient(
        "https://cms.example/subdir", "user", "password",
        post_type=CUSTOM_POST_TYPE, rest_base=CUSTOM_REST_BASE,
        transport=httpx.MockTransport(
            lambda req: calls.append(req) or httpx.Response(200, json=response),
        ),
    )
    assert port.trash("1")["status"] == "trash"
    assert calls[0].method == "DELETE"
    assert calls[0].url.path == f"/subdir/wp-json/wp/v2/{CUSTOM_REST_BASE}/1"
    assert calls[0].url.params["force"] == "false"
