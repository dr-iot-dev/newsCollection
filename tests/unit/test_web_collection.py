import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import (
    ExtractionResult,
    Item,
    ItemVersion,
    LegalStatus,
    ModuleMessage,
    RawSnapshot,
    RobotsSnapshot,
    Source,
    SourceCursor,
    TermsSnapshot,
)
from app.modules.acquisition.service import collect_source
from app.orchestration.phase2 import process_phase2
from app.sources.config import load_sources
from app.sources.service import sync_sources
from tests.unit.test_acquisition_service import count, factory

FIXTURE = Path("tests/fixtures/phase2")
ROBOTS = "User-agent: *\nDisallow: /private\nDisallow: /news/2026/blocked\nAllow: /news/\n"


def web_source(session: Session, **updates):
    source = session.scalars(select(Source).where(Source.key == "vendor-newsroom")).one()
    source.enabled, source.legal_status = True, LegalStatus.APPROVED
    source.terms_checked_at = datetime.now(UTC)
    source.config = {
        **source.config,
        "selectors": {
            "list_links": "main a.news-card",
            "title": "h1",
            "published_at": "time[datetime]",
            "body": "article .content",
        },
        "legal": {
            **source.config["legal"],
            "status": "approved",
            "approved_by": "test-reviewer",
            "robots_reviewed_at": datetime.now(UTC).isoformat(),
        },
        **updates,
    }
    session.commit()
    return source


def handler_for(
    requests,
    *,
    robots=ROBOTS,
    terms="Approved collection terms",
    article=None,
    redirect=None,
    listing=None,
):
    def handler(request):
        path = request.url.path
        requests.append(path)
        if path == "/robots.txt":
            return httpx.Response(200, text=robots, headers={"Content-Type": "text/plain"})
        if path == "/terms":
            return httpx.Response(
                200, text="<main>" + terms + "</main>", headers={"Content-Type": "text/html"}
            )
        if path == "/news/":
            return httpx.Response(
                200,
                text=listing or (FIXTURE / "list.html").read_text(),
                headers={"Content-Type": "text/html"},
            )
        if redirect:
            return httpx.Response(302, headers={"Location": redirect})
        return httpx.Response(
            200,
            text=article or (FIXTURE / "article.html").read_text(),
            headers={"Content-Type": "text/html"},
        )

    return handler


def run(session, requests, **options):
    handler = options.pop("handler", handler_for(requests))
    result = collect_source(
        session, "vendor-newsroom", force=True, http_factory=factory(handler), **options
    )
    session.commit()
    return result


def test_web_disallowed_and_external_urls_never_requested_and_versions_idempotent(
    acquisition_session: Session,
) -> None:
    session = acquisition_session
    web_source(session)
    requests = []
    for _ in range(3):
        assert run(session, requests).status == "success"
    assert set(requests) == {"/robots.txt", "/terms", "/news/", "/news/2026/x1"}
    assert count(session, Item) == count(session, ItemVersion) == count(session, ModuleMessage) == 1
    assert count(session, RobotsSnapshot) == count(session, TermsSnapshot) == 3
    assert count(session, RawSnapshot) == 6
    result = run(
        session,
        requests,
        handler=handler_for(
            requests,
            article=(FIXTURE / "article.html")
            .read_text()
            .replace("Pricing is described", "Pricing will be described"),
        ),
    )
    assert result.updated == 1 and count(session, ItemVersion) == 2
    assert process_phase2(session)["extraction"] == 2
    session.commit()
    assert process_phase2(session) == {"extraction": 0, "deduplication": 0}


@pytest.mark.parametrize("status", [404, 503])
def test_robots_errors_prevent_all_body_requests(acquisition_session: Session, status: int) -> None:
    session = acquisition_session
    web_source(session)
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(status)

    result = run(session, requests, handler=handler)
    assert result.status == "failed" and set(requests) == {"/robots.txt"}
    assert count(session, Item) == count(session, RawSnapshot) == 0


@pytest.mark.parametrize(
    "redirect", ["/news/2026/blocked", "https://evil.example/news/2026/x2", "/login"]
)
def test_redirect_target_is_gated_before_get(acquisition_session: Session, redirect: str) -> None:
    session = acquisition_session
    web_source(session)
    requests = []
    result = run(session, requests, handler=handler_for(requests, redirect=redirect))
    assert result.status == "failed"
    assert requests == ["/robots.txt", "/terms", "/news/", "/news/2026/x1"]
    assert count(session, Item) == 0


@pytest.mark.parametrize("changed", ["terms", "robots"])
def test_document_change_requires_new_review_and_sync_cannot_bypass(
    acquisition_session: Session, changed: str
) -> None:
    session = acquisition_session
    source = web_source(session)
    requests = []
    assert run(session, requests).status == "success"
    requests.clear()
    options = {
        changed: "Updated collection terms" if changed == "terms" else ROBOTS + "Disallow: /other\n"
    }
    result = run(session, requests, handler=handler_for(requests, **options))
    assert result.error_code == "LEGAL_DOCUMENT_CHANGED"
    assert source.legal_status == LegalStatus.PENDING
    assert requests == ["/robots.txt", "/terms"]
    config = load_sources(Path("config/sources.example.yaml"))
    web = next(s for s in config.sources if s.key == source.key)
    # Reusing the old approval evidence is rejected during synchronization.
    web.enabled = True
    web.legal.status = "approved"
    web.legal.approved_by = "test-reviewer"
    web.legal.terms_reviewed_at = source.terms_checked_at
    web.legal.robots_reviewed_at = datetime.fromisoformat(
        source.config["legal"]["robots_reviewed_at"]
    )
    preview = sync_sources(session, config, dry_run=True)
    assert next(action for action in preview if action.key == source.key).legal_status == "pending"
    actions = sync_sources(session, config, dry_run=False)
    assert next(action for action in actions if action.key == source.key).legal_status == "pending"
    session.commit()
    assert source.legal_status == LegalStatus.PENDING
    new_review = datetime.now(UTC) + timedelta(seconds=1)
    web.legal.terms_reviewed_at = web.legal.robots_reviewed_at = new_review
    sync_sources(session, config, dry_run=False)
    session.commit()
    assert source.legal_status == LegalStatus.APPROVED
    assert run(session, requests, handler=handler_for(requests, **options)).status == "success"


def test_web_dry_run_keeps_all_storage_unchanged(acquisition_session: Session) -> None:
    session = acquisition_session
    web_source(session)
    result = run(session, [], dry_run=True)
    assert result.status == "dry_run" and result.created == 1
    for model in (
        Item,
        ItemVersion,
        RawSnapshot,
        RobotsSnapshot,
        TermsSnapshot,
        SourceCursor,
        ModuleMessage,
    ):
        assert count(session, model) == 0


def test_page_budget_preserves_queue_and_resumes(acquisition_session: Session) -> None:
    session = acquisition_session
    source = web_source(session, max_pages_per_run=2)
    requests = []
    listing = (
        "<main>"
        + "".join(f'<a class="news-card" href="/news/2026/{i}">{i}</a>' for i in range(4))
        + "</main>"
    )
    for _ in range(4):
        requests.clear()
        assert (
            run(session, requests, handler=handler_for(requests, listing=listing)).status
            == "success"
        )
        assert len(requests) == 4  # two control documents and two content requests
    assert count(session, Item) == 4
    assert session.get(SourceCursor, source.id).cursor_json["pending"]


def test_not_modified_list_still_checks_detail_updates(acquisition_session: Session) -> None:
    session = acquisition_session
    web_source(session)
    calls = []
    original = handler_for(calls)

    def initial(request):
        response = original(request)
        if request.url.path in {"/news/", "/news/2026/x1"}:
            response.headers["ETag"] = '"initial"'
        return response

    assert run(session, calls, handler=initial).created == 1
    calls.clear()
    updated = handler_for(
        calls,
        article=(FIXTURE / "article.html")
        .read_text()
        .replace("Pricing is described", "Pricing will be described"),
    )

    def second(request):
        if request.url.path == "/news/":
            assert request.headers["If-None-Match"] == '"initial"'
            calls.append("/news/")
            return httpx.Response(304)
        if request.url.path == "/news/2026/x1":
            assert request.headers["If-None-Match"] == '"initial"'
        return updated(request)

    assert run(session, calls, handler=second).updated == 1
    assert calls == ["/robots.txt", "/terms", "/news/", "/news/2026/x1"]


def test_same_origin_pagination_resumes_without_repeating_page_one_forever(
    acquisition_session: Session,
) -> None:
    session = acquisition_session
    web_source(
        session,
        max_pages_per_run=3,
        selectors={
            "list_links": "main a.news-card",
            "title": "h1",
            "published_at": "time[datetime]",
            "body": "article .content",
            "next_page": "a.next",
        },
    )
    calls = []
    fallback = handler_for(calls)

    def handler(request):
        if request.url.path == "/news/" and request.url.params.get("page") == "2":
            calls.append("/news/?page=2")
            return httpx.Response(
                200,
                text='<main><a class="news-card" href="/news/2026/two">Two</a></main>',
                headers={"Content-Type": "text/html"},
            )
        if request.url.path == "/news/":
            calls.append("/news/")
            return httpx.Response(
                200,
                text=(
                    '<main><a class="news-card" href="/news/2026/x1">One</a>'
                    '<a class="next" href="?page=2">Next</a></main>'
                ),
                headers={"Content-Type": "text/html"},
            )
        return fallback(request)

    for _ in range(2):
        assert run(session, calls, handler=handler).status == "success"
    assert count(session, Item) == 2
    assert "/news/2026/two" in calls


def test_redirects_count_toward_content_page_budget(acquisition_session: Session) -> None:
    session = acquisition_session
    web_source(session, max_pages_per_run=2)
    calls = []
    result = run(session, calls, handler=handler_for(calls, redirect="/news/2026/redirected"))
    assert result.error_code == "PAGE_LIMIT"
    assert "/news/2026/redirected" not in calls
    assert count(session, Item) == 0


def test_listing_disallow_and_robots_timeout_block_before_page_get(
    acquisition_session: Session,
) -> None:
    session = acquisition_session
    web_source(session)
    calls = []
    result = run(
        session, calls, handler=handler_for(calls, robots="User-agent: *\nDisallow: /news/\n")
    )
    assert result.error_code == "ROBOTS_DISALLOW" and "/news/" not in calls
    calls.clear()

    def timeout(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("timeout")

    result = run(session, calls, handler=timeout)
    assert result.status == "failed" and set(calls) == {"/robots.txt"}


def test_nul_in_web_html_is_stored_and_extracted_with_original_byte_hash(
    acquisition_session: Session,
) -> None:
    session = acquisition_session
    web_source(session)
    requests = []
    article = (
        (FIXTURE / "article.html")
        .read_text(encoding="utf-8")
        .replace("Pricing is described", "Pricing\x00 is described")
    )
    listing = (FIXTURE / "list.html").read_text(encoding="utf-8") + "<!--\x00-->"
    result = run(session, requests, handler=handler_for(requests, article=article, listing=listing))
    assert result.status == "success" and result.created == 1
    snapshots = list(session.scalars(select(RawSnapshot)))
    assert len(snapshots) == 2
    for snapshot in snapshots:
        original = listing if snapshot.requested_url.endswith("/news/") else article
        assert snapshot.body_sha256 == hashlib.sha256(original.encode()).hexdigest()
        assert "\x00" not in snapshot.body_text and "\ufffd" in snapshot.body_text
    item = session.scalars(select(Item)).one()
    version = session.scalars(select(ItemVersion)).one()
    assert "\x00" not in item.content_text and "\ufffd" in item.content_text
    assert "\x00" not in version.content_text and "\ufffd" in version.content_text
    assert process_phase2(session)["extraction"] == 1
    session.commit()
    extracted = session.scalars(select(ExtractionResult)).one()
    assert "\x00" not in extracted.payload_json["body"]
    assert "\ufffd" in extracted.payload_json["body"]
