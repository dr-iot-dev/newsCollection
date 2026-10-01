"""Permission-gated, bounded static HTML collection. No browser or subresource loading."""

import hashlib
import re
from collections import deque
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup
from pydantic import AnyHttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.acquisition_v1 import AcquisitionResultV1
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.core.content import normalize_text, normalize_url
from app.infrastructure.db.models import (
    JobRun,
    LegalStatus,
    RobotsSnapshot,
    Source,
    SourceCursor,
    TermsSnapshot,
)
from app.infrastructure.db.repositories.audit import AuditEventWriter
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.modules.acquisition.connectors import DiscoveredEntry, decode_text
from app.modules.acquisition.http import CollectionError, FetchResponse, SafeHttpClient
from app.modules.acquisition.robots import RobotsPolicy
from app.modules.acquisition.service import (
    CollectionResult,
    HttpFactory,
    store_snapshot,
    upsert_entry,
    utc,
)
from app.sources.config import WebSource


def origin(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc.lower()}"


def html(response: FetchResponse) -> BeautifulSoup:
    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if mime not in {"text/html", "application/xhtml+xml"}:
        raise CollectionError("UNSUPPORTED_HTML_TYPE")
    return BeautifulSoup(decode_text(response), "html.parser")


def terms_hash(response: FetchResponse) -> str:
    document = html(response)
    for node in document.select("script, style, noscript, nav, footer"):
        node.decompose()
    text = normalize_text(document.get_text(" ", strip=True))
    if not text:
        raise CollectionError("TERMS_INVALID")
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


class WebGuard:
    def __init__(self, config: WebSource, client: SafeHttpClient, robots: RobotsPolicy) -> None:
        self.config, self.client, self.robots = config, client, robots
        self.count = 0
        self.origin = origin(str(client.policy.validate(config.list_url)))
        self.allow = [re.compile(p) for p in config.allow_url_patterns]
        self.deny = [re.compile(p) for p in config.deny_url_patterns]

    def validate(self, value: str, *, listing: bool = False) -> str:
        value = str(self.client.policy.validate(value))
        if origin(value) != self.origin or any(p.search(value) for p in self.deny):
            raise CollectionError("WEB_URL_BLOCKED")
        if listing and urlsplit(value).path != urlsplit(self.config.list_url).path:
            raise CollectionError("WEB_LIST_URL_BLOCKED")
        if not listing and not any(p.search(value) for p in self.allow):
            raise CollectionError("WEB_URL_BLOCKED")
        if not self.robots.allowed(value):
            raise CollectionError("ROBOTS_DISALLOW")
        return value

    def request_guard(self, value: str, *, listing: bool) -> None:
        self.validate(value, listing=listing)
        if self.count >= self.config.max_pages_per_run:
            raise CollectionError("PAGE_LIMIT")
        self.count += 1


def legal_gate(
    session: Session,
    source: Source,
    config: WebSource,
    client: SafeHttpClient,
    cursor: SourceCursor | None,
    current: datetime,
    dry_run: bool,
) -> tuple[RobotsPolicy, dict[str, Any]]:
    base = origin(str(client.policy.validate(config.list_url)))

    # Control documents are restricted to the same approved origin, including redirects.
    def control_guard(value: str) -> None:
        if origin(str(client.policy.validate(value))) != base:
            raise CollectionError("CONTROL_ORIGIN_BLOCKED")

    control_guard(config.legal.terms_url)
    response = client.get(base + "/robots.txt", url_guard=control_guard)
    if len(response.body) > 512_000 or response.status_code != 200:
        raise CollectionError("ROBOTS_INVALID")
    robots = RobotsPolicy(
        response.body.decode("utf-8", errors="strict"), config.user_agent or "CompanyNewsBot/1.0"
    )
    client.min_delay_seconds = max(client.min_delay_seconds, robots.delay)
    if not robots.allowed(config.legal.terms_url):
        raise CollectionError("ROBOTS_DISALLOW_TERMS")

    def terms_guard(value: str) -> None:
        control_guard(value)
        if not robots.allowed(value):
            raise CollectionError("ROBOTS_DISALLOW_TERMS")

    terms = client.get(config.legal.terms_url, url_guard=terms_guard)
    if terms.status_code != 200:
        raise CollectionError("TERMS_INVALID")
    hashes = {
        "robots": "sha256:" + hashlib.sha256(response.body).hexdigest(),
        "terms": terms_hash(terms),
    }
    previous = (cursor.cursor_json if cursor else {}).get("web_gate", {})
    changed = bool(previous) and any(previous.get(k) != v for k, v in hashes.items())
    reviewed = min(
        utc(config.legal.terms_reviewed_at or current),
        utc(config.legal.robots_reviewed_at or current),
    )
    reapproved = previous.get("checked_at") and reviewed > datetime.fromisoformat(
        previous["checked_at"]
    )
    pending = changed and not reapproved
    if not dry_run:
        robot_row = RobotsSnapshot(
            origin=base,
            url=response.final_url,
            body_hash=hashes["robots"],
            decision="changed" if pending else "allowed",
            fetched_at=current,
            reviewed_at=config.legal.robots_reviewed_at,
        )
        session.add(robot_row)
        session.add(
            TermsSnapshot(
                source_id=source.id,
                url=terms.final_url,
                body_hash=hashes["terms"],
                decision="changed" if pending else "approved",
                checked_at=current,
            )
        )
        session.flush()
        if cursor is None:
            cursor = SourceCursor(source_id=source.id, cursor_json={})
            session.add(cursor)
        gate = {**hashes, "checked_at": current.isoformat(), "blocked": pending}
        cursor.cursor_json = {**cursor.cursor_json, "web_gate": gate}
        cursor.robots_snapshot_id = robot_row.id
        if pending:
            source.legal_status = LegalStatus.PENDING
            AuditEventWriter(session).append(
                actor_type="system",
                actor_id="acquisition",
                action="source.legal_changed",
                entity_type="source",
                entity_id=str(source.id),
                trace_id=str(robot_row.id),
                after={"legal_status": "pending"},
            )
        session.flush()
    if pending:
        raise CollectionError("LEGAL_DOCUMENT_CHANGED")
    return robots, {**hashes, "checked_at": current.isoformat(), "blocked": False}


def collect_web(
    session: Session,
    source: Source,
    config: WebSource,
    *,
    http_factory: HttpFactory,
    dry_run: bool,
    force: bool,
    current: datetime,
) -> CollectionResult:
    previous_job = session.scalar(
        select(JobRun)
        .where(JobRun.source_id == source.id)
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    if previous_job and previous_job.stats_json.get("not_before"):
        barrier = datetime.fromisoformat(previous_job.stats_json["not_before"])
        if utc(barrier) > current:
            return CollectionResult(source.key, "deferred", next_run_at=utc(barrier))
    if source.next_run_at and utc(source.next_run_at) > current and not force:
        return CollectionResult(source.key, "deferred", next_run_at=utc(source.next_run_at))
    cursor = session.get(SourceCursor, source.id)
    config_hash = canonical_payload_hash(source.config)
    saved = (
        cursor.cursor_json
        if cursor and cursor.cursor_json.get("config_hash") == config_hash
        else {}
    )
    pages: dict[str, Any] = dict(saved.get("pages", {}))
    job = JobRun(
        job_type="acquisition",
        source_id=source.id,
        scheduled_for=current,
        started_at=current,
        status="running",
        idempotency_key=f"web:{source.id}:{uuid4()}",
    )
    if not dry_run:
        session.add(job)
        session.flush()
    client = http_factory(config)
    next_run = current + timedelta(minutes=config.interval_minutes or 60)
    snapshots = 0
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    try:
        robots, gate = legal_gate(session, source, config, client, cursor, current, dry_run)
        cursor = session.get(SourceCursor, source.id)
        guard = WebGuard(config, client, robots)
        queue: deque[tuple[str, bool]] = deque([(config.list_url, True)])
        queue.extend((url, listing) for url, listing in saved.get("pending", []))
        visited: set[str] = set()
        decoded = []
        total_bytes = 0
        while queue and guard.count < config.max_pages_per_run:
            url, listing = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            guard.validate(url, listing=listing)
            cached = pages.get(url, {})
            response = client.get(
                url,
                etag=cached.get("etag"),
                last_modified=cached.get("last_modified"),
                url_guard=partial(guard.request_guard, listing=listing),
            )
            total_bytes += len(response.body)
            if total_bytes > (config.max_response_bytes or 5_242_880):
                raise CollectionError("RUN_TOO_LARGE")
            snapshot = None if dry_run else store_snapshot(session, source.id, response)
            snapshots += int(snapshot is not None)
            if response.status_code == 304 and not cached:
                raise CollectionError("UNEXPECTED_NOT_MODIFIED")
            links: list[str] = []
            following: str | None = None
            if listing:
                if response.status_code == 304:
                    links, following = cached.get("links", []), cached.get("next_url")
                else:
                    document = html(response)
                    nodes = document.select(config.selectors.list_links)
                    if len(nodes) > 1000:
                        raise CollectionError("WEB_LIST_TOO_LARGE")
                    for node in nodes:
                        href = node.get("href")
                        if not isinstance(href, str):
                            continue
                        try:
                            link = guard.validate(urljoin(response.final_url, href))
                        except CollectionError:
                            continue
                        if link not in links:
                            links.append(link)
                    if config.selectors.next_page:
                        next_node = document.select_one(config.selectors.next_page)
                        href = next_node.get("href") if next_node else None
                        if isinstance(href, str):
                            following = guard.validate(
                                urljoin(response.final_url, href), listing=True
                            )
                queue.extend((link, False) for link in links)
                if following and following not in visited:
                    queue.append((following, True))
            elif response.status_code != 304:
                document = html(response)
                title_node = document.select_one(config.selectors.title) or document.select_one(
                    "h1, title"
                )
                title = (
                    normalize_text(title_node.get_text(" ", strip=True))
                    if title_node
                    else "Untitled"
                )
                canonical = normalize_url(response.final_url)
                entry = DiscoveredEntry(
                    external_id=normalize_url(url),
                    canonical_url=canonical,
                    title=title[:1000],
                    content=decode_text(response),
                    published_at=None,
                    language=config.language_hint or "und",
                    metadata={"format": "html"},
                )
                decoded.append((entry, snapshot))
            pages[url] = {
                "etag": response.headers.get("etag", cached.get("etag"))
                if response.status_code == 304
                else response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified", cached.get("last_modified"))
                if response.status_code == 304
                else response.headers.get("last-modified"),
                "links": links,
                "next_url": following,
            }
        with session.begin_nested():
            for entry, snapshot in decoded:
                action = upsert_entry(session, source.id, entry, snapshot, dry_run=dry_run)
                counts[action] += 1
                if action != "unchanged" and snapshot:
                    payload = AcquisitionResultV1(
                        snapshot_id=snapshot.id,
                        source_id=source.id,
                        final_url=AnyHttpUrl(snapshot.final_url),
                        fetched_at=snapshot.fetched_at,
                        content_sha256=snapshot.body_sha256,
                    )
                    envelope = ContractEnvelope[AcquisitionResultV1].build(
                        payload,
                        contract_type="AcquisitionResult",
                        producer="acquisition",
                        producer_version="0.2.0",
                        correlation_id=job.id,
                    )
                    ModuleMessageRepository(session).enqueue_once(envelope, consumer="extraction")
            if not dry_run:
                assert cursor is not None
                pending = list(
                    dict.fromkeys((url, listing) for url, listing in queue if url not in visited)
                )
                if len(pending) > 1000:
                    raise CollectionError("WEB_QUEUE_TOO_LARGE")
                cursor.cursor_json = {
                    "config_hash": config_hash,
                    "pages": dict(list(pages.items())[-1000:]),
                    "pending": pending,
                    "web_gate": gate,
                }
                source.last_success_at, source.next_run_at = current, next_run
                job.status, job.finished_at, job.stats_json = "success", datetime.now(UTC), counts
                AuditEventWriter(session).append(
                    actor_type="system",
                    actor_id="acquisition",
                    action="source.collected",
                    entity_type="source",
                    entity_id=str(source.id),
                    trace_id=str(job.id),
                    after=counts,
                )
        return CollectionResult(
            source.key,
            "dry_run" if dry_run else "success",
            created=counts["created"],
            updated=counts["updated"],
            unchanged=counts["unchanged"],
            snapshots=snapshots,
            next_run_at=next_run,
        )
    except (CollectionError, UnicodeDecodeError) as exc:
        code = exc.code if isinstance(exc, CollectionError) else "ROBOTS_INVALID_ENCODING"
        retry = exc.retry_at if isinstance(exc, CollectionError) else None
        if not dry_run:
            source.next_run_at = retry or next_run
            job.status, job.finished_at, job.error_code = "failed", datetime.now(UTC), code
            job.stats_json = {"not_before": retry.isoformat() if retry else None}
            AuditEventWriter(session).append(
                actor_type="system",
                actor_id="acquisition",
                action="source.collection_failed",
                entity_type="source",
                entity_id=str(source.id),
                trace_id=str(job.id),
                after={"error_code": code},
            )
        return CollectionResult(
            source.key,
            "failed",
            snapshots=snapshots,
            error_code=code,
            next_run_at=retry or next_run,
        )
    finally:
        client.close()
