from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import (
    AuditEvent,
    Item,
    ItemVersion,
    JobRun,
    LegalStatus,
    ModuleMessage,
    RawSnapshot,
    Source,
    SourceCursor,
)
from app.modules.acquisition.http import SafeHttpClient
from app.modules.acquisition.service import collect_source
from app.sources.config import SourceConfig, load_sources
from app.sources.service import sync_sources

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>News</title><language>en</language>
<item><guid>release-1</guid><title>Product released</title>
<link>https://vendor.example/news/one</link>
<pubDate>Wed, 30 Sep 2026 08:00:00 +0900</pubDate>
<description><![CDATA[<p>Feature one</p><script>evil()</script>]]></description>
</item></channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom">
<title>News</title><entry><id>urn:release:one</id><title>Product released</title>
<link href="https://vendor.example/news/one"/>
<published>2026-09-30T08:00:00+09:00</published><updated>2026-09-30T09:00:00+09:00</updated>
<content type="html">&lt;p&gt;Feature one&lt;/p&gt;</content></entry></feed>"""


def factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[SourceConfig], SafeHttpClient]:
    return lambda _: SafeHttpClient(
        allowed_hosts=["vendor.example", "api.github.com"],
        user_agent="TestNewsBot/1.0",
        resolver=lambda _: ["93.184.216.34"],
        transport=httpx.MockTransport(handler),
        min_delay_seconds=0,
        sleep=lambda _: None,
    )


def feed_factory(body: bytes = RSS) -> Callable[[SourceConfig], SafeHttpClient]:
    return factory(
        lambda _: httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "application/rss+xml", "ETag": '"one"'},
        )
    )


def count(session: Session, model: object) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0  # type: ignore[arg-type]


def run(
    session: Session, http_factory: Callable[[SourceConfig], SafeHttpClient], **options: object
):
    result = collect_source(
        session, "vendor-official-feed", force=True, http_factory=http_factory, **options
    )  # type: ignore[arg-type]
    session.commit()
    return result


@pytest.mark.parametrize("body", [RSS, ATOM])
def test_three_identical_fetches_only_create_one_item_and_version(
    acquisition_session: Session,
    body: bytes,
) -> None:
    session = acquisition_session
    for _ in range(3):
        assert run(session, feed_factory(body)).status == "success"
    assert count(session, Item) == 1
    assert count(session, ItemVersion) == 1
    assert count(session, RawSnapshot) == 3
    assert count(session, ModuleMessage) == 1
    assert count(session, AuditEvent) == 3
    item = session.scalars(select(Item)).one()
    assert item.version == 1
    assert item.content_text == "Feature one"
    assert item.published_at is not None
    assert item.published_at.replace(tzinfo=UTC).hour == 23
    assert session.get(SourceCursor, item.source_id).etag == '"one"'
    result = run(session, feed_factory(body.replace(b"Feature one", b"Feature two")))
    assert result.updated == 1
    assert count(session, Item) == 1
    assert count(session, ItemVersion) == 2
    assert count(session, ModuleMessage) == 2
    versions = list(session.scalars(select(ItemVersion).order_by(ItemVersion.version_no)))
    assert [version.content_text for version in versions] == ["Feature one", "Feature two"]


def test_missing_guid_uses_stable_link_id(acquisition_session: Session) -> None:
    body = RSS.replace(b"<guid>release-1</guid>", b"")
    for _ in range(3):
        run(acquisition_session, feed_factory(body))
    assert count(acquisition_session, Item) == 1
    assert acquisition_session.scalars(select(Item.external_id)).one() == (
        "https://vendor.example/news/one"
    )


def test_missing_guid_and_link_uses_stable_hash(acquisition_session: Session) -> None:
    body = RSS.replace(b"<guid>release-1</guid>", b"").replace(
        b"<link>https://vendor.example/news/one</link>",
        b"",
    )
    for _ in range(3):
        run(acquisition_session, feed_factory(body))
    assert count(acquisition_session, Item) == 1
    assert acquisition_session.scalars(select(Item.external_id)).one().startswith("sha256:")


def test_not_modified_uses_validators_and_does_not_add_items(acquisition_session: Session) -> None:
    session = acquisition_session
    run(session, feed_factory())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["if-none-match"] == '"one"'
        return httpx.Response(304)

    result = run(session, factory(handler))
    assert result.status == "not_modified"
    assert count(session, Item) == count(session, ItemVersion) == 1
    assert count(session, RawSnapshot) == 2
    item = session.scalars(select(Item)).one()
    assert session.get(SourceCursor, item.source_id).etag == '"one"'


@pytest.mark.parametrize(
    "body",
    [
        b"<rss><unclosed>",
        b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel>&x;</channel></rss>',
        RSS.replace(b"https://vendor.example/news/one", b"https://evil.example/news/one"),
    ],
)
def test_failed_parse_or_unsafe_entry_retains_raw_but_not_cursor(
    acquisition_session: Session,
    body: bytes,
) -> None:
    session = acquisition_session
    run(session, feed_factory())
    source = session.scalars(select(Source).where(Source.key == "vendor-official-feed")).one()
    before = session.get(SourceCursor, source.id).cursor_json.copy()
    result = run(session, feed_factory(body))
    assert result.status == "failed"
    assert count(session, Item) == count(session, ItemVersion) == 1
    assert count(session, RawSnapshot) == 2
    assert session.get(SourceCursor, source.id).cursor_json == before
    assert list(session.scalars(select(JobRun.status).order_by(JobRun.started_at)))[-1] == "failed"


def test_dry_run_makes_no_persistent_changes(acquisition_session: Session) -> None:
    session = acquisition_session
    result = run(session, feed_factory(), dry_run=True)
    assert result.status == "dry_run" and result.created == 1
    for model in (Item, ItemVersion, RawSnapshot, SourceCursor, JobRun, ModuleMessage, AuditEvent):
        assert count(session, model) == 0
    source = session.scalars(select(Source).where(Source.key == "vendor-official-feed")).one()
    assert source.last_success_at is None and source.next_run_at is None


@pytest.mark.parametrize("state", ["disabled", "pending", "blocked", "expired"])
def test_legal_gate_prevents_http(acquisition_session: Session, state: str) -> None:
    session = acquisition_session
    source = session.scalars(select(Source).where(Source.key == "vendor-official-feed")).one()
    if state == "disabled":
        source.enabled = False
    elif state == "expired":
        source.terms_checked_at = datetime.now(UTC) - timedelta(days=181)
    else:
        source.legal_status = LegalStatus(state)
    session.commit()

    def no_http(_: SourceConfig) -> SafeHttpClient:
        pytest.fail("A blocked source must never create an HTTP client")

    result = run(session, no_http)
    assert result.status == "blocked"
    assert count(session, JobRun) == 0


def release(release_id: int = 1, **changes: object) -> dict[str, object]:
    return {
        "id": release_id,
        "html_url": f"https://github.com/esphome/esphome/releases/tag/v{release_id}",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-09-30T00:00:00Z",
        "updated_at": "2026-09-30T00:00:00Z",
        "name": f"Version {release_id}",
        "tag_name": f"v{release_id}",
        "body": "Release notes",
        **changes,
    }


def github_run(
    session: Session, handler: Callable[[httpx.Request], httpx.Response], **options: object
):
    result = collect_source(
        session, "github-esphome", force=True, http_factory=factory(handler), **options
    )  # type: ignore[arg-type]
    session.commit()
    return result


def test_github_filters_and_updates_versions(acquisition_session: Session) -> None:
    session = acquisition_session
    bodies = [release(), release(2, prerelease=True), release(3, draft=True)]
    for _ in range(3):
        assert github_run(session, lambda _: httpx.Response(200, json=bodies)).created in (0, 1)
    assert count(session, Item) == count(session, ItemVersion) == 1
    bodies[0]["body"] = "Updated notes"
    result = github_run(session, lambda _: httpx.Response(200, json=bodies))
    assert result.updated == 1
    assert count(session, Item) == 1 and count(session, ItemVersion) == 2
    bodies[0]["updated_at"] = "2026-09-30T01:00:00Z"
    assert github_run(session, lambda _: httpx.Response(200, json=bodies)).updated == 1
    assert count(session, ItemVersion) == 3
    source = session.scalars(select(Source).where(Source.key == "github-esphome")).one()
    source.config = {**source.config, "include_prereleases": True, "include_drafts": True}
    session.commit()
    assert github_run(session, lambda _: httpx.Response(200, json=bodies)).created == 2


def test_github_pagination_checks_every_page_even_when_first_is_304(
    acquisition_session: Session,
) -> None:
    session = acquisition_session

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-github-api-version"] == "2026-03-10"
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[release(2)], headers={"ETag": '"page2"'})
        return httpx.Response(
            200,
            json=[release()],
            headers={
                "ETag": '"page1"',
                "Link": (
                    "<https://api.github.com/repos/esphome/esphome/releases"
                    '?per_page=100&page=2>; rel="next"'
                ),
            },
        )

    assert github_run(session, handler).created == 2
    calls: list[httpx.Request] = []

    def changed(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.params.get("page") == "2":
            assert request.headers["if-none-match"] == '"page2"'
            return httpx.Response(200, json=[release(2, body="Changed on second page")])
        assert request.headers["if-none-match"] == '"page1"'
        return httpx.Response(304)

    result = github_run(session, changed)
    assert result.updated == 1 and len(calls) == 2
    assert count(session, Item) == 2 and count(session, ItemVersion) == 3


def test_failed_second_page_is_atomic(acquisition_session: Session) -> None:
    session = acquisition_session

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200, content=b"{broken", headers={"Content-Type": "application/json"}
            )
        return httpx.Response(
            200,
            json=[release()],
            headers={
                "Link": (
                    '<https://api.github.com/repos/esphome/esphome/releases?page=2>; rel="next"'
                ),
            },
        )

    assert github_run(session, handler).status == "failed"
    assert count(session, Item) == count(session, ItemVersion) == count(session, SourceCursor) == 0
    assert count(session, RawSnapshot) == 2


def test_rate_limit_blocks_force_until_reset(acquisition_session: Session) -> None:
    session = acquisition_session
    reset = datetime.now(UTC) + timedelta(hours=2)
    result = github_run(
        session,
        lambda _: httpx.Response(
            429,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(reset.timestamp())),
            },
        ),
    )
    assert result.error_code == "RATE_LIMITED"
    assert result.next_run_at is not None and result.next_run_at.timestamp() >= int(
        reset.timestamp()
    )

    def no_http(_: httpx.Request) -> httpx.Response:
        pytest.fail("Force must not override a server rate limit")

    assert github_run(session, no_http).status == "deferred"


def test_configuration_defaults_and_legal_evidence_are_persisted(
    acquisition_session: Session,
) -> None:
    config = load_sources(Path("config/sources.example.yaml"))
    config.defaults.user_agent = "ChangedCompanyNewsBot/1.0"
    sync_sources(acquisition_session, config, dry_run=False)
    source = acquisition_session.scalars(select(Source).where(Source.key == "github-esphome")).one()
    assert source.config["user_agent"] == config.defaults.user_agent
    assert source.config["interval_minutes"] == config.defaults.interval_minutes
    assert source.config["legal"]["approved_by"] == "editor@example.jp"


@pytest.mark.parametrize("acquisition_engine", ["postgresql"], indirect=True)
def test_concurrent_postgres_collection_is_idempotent(
    acquisition_session: Session,
    acquisition_engine: Engine,
) -> None:
    def worker(_: int) -> str:
        with Session(acquisition_engine) as session, session.begin():
            return collect_source(
                session,
                "vendor-official-feed",
                force=True,
                http_factory=feed_factory(),
            ).status

    with ThreadPoolExecutor(max_workers=3) as workers:
        assert list(workers.map(worker, range(3))) == ["success"] * 3
    assert count(acquisition_session, Item) == count(acquisition_session, ItemVersion) == 1
    assert count(acquisition_session, RawSnapshot) == 3


@pytest.mark.parametrize(
    "body",
    [
        ATOM.replace(
            b'<content type="html">&lt;p&gt;Feature one&lt;/p&gt;</content>',
            b'<content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">'
            b"<p>Feature one</p><script>evil()</script></div></content>",
        ),
        RSS.replace(b'encoding="UTF-8"', b'encoding="ISO-8859-1"').replace(
            b"Feature one", b"Caf\xe9"
        ),
    ],
)
def test_xhtml_and_declared_encoding(acquisition_session: Session, body: bytes) -> None:
    result = run(acquisition_session, feed_factory(body))
    assert result.created == 1
    item = acquisition_session.scalars(select(Item)).one()
    assert "evil()" not in item.content_text
    assert item.content_text in {"Feature one", "Café"}
    snapshot = acquisition_session.scalars(select(RawSnapshot)).one()
    assert "\ufffd" not in snapshot.body_text


def test_successful_last_rate_limit_request_still_defers_force(
    acquisition_session: Session,
) -> None:
    reset = datetime.now(UTC) + timedelta(hours=2)
    result = github_run(
        acquisition_session,
        lambda _: httpx.Response(
            200,
            json=[release()],
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(reset.timestamp())),
            },
        ),
    )
    assert result.created == 1

    def no_http(_: httpx.Request) -> httpx.Response:
        pytest.fail("Successful exhausted rate limit must not be bypassed")

    assert github_run(acquisition_session, no_http).status == "deferred"


@pytest.mark.parametrize("changes", [{"published_at": 123}, {"updated_at": {}}, {"id": True}])
def test_malformed_release_metadata_fails_safely(
    acquisition_session: Session, changes: dict
) -> None:
    result = github_run(
        acquisition_session, lambda _: httpx.Response(200, json=[release(**changes)])
    )
    assert result.error_code == "PARSE_ERROR"
    assert count(acquisition_session, Item) == count(acquisition_session, SourceCursor) == 0


def test_page_limit_does_not_commit_partial_items(acquisition_session: Session) -> None:
    source = acquisition_session.scalars(select(Source).where(Source.key == "github-esphome")).one()
    source.config = {**source.config, "max_pages_per_run": 1}
    acquisition_session.commit()
    result = github_run(
        acquisition_session,
        lambda _: httpx.Response(
            200,
            json=[release()],
            headers={
                "Link": (
                    '<https://api.github.com/repos/esphome/esphome/releases?page=2>; rel="next"'
                ),
            },
        ),
    )
    assert result.error_code == "PAGE_LIMIT"
    assert count(acquisition_session, Item) == count(acquisition_session, SourceCursor) == 0
    assert count(acquisition_session, RawSnapshot) == 1
