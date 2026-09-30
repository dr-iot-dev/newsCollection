"""One source per transaction, serialized by its database row lock."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.acquisition_v1 import AcquisitionResultV1
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.infrastructure.db.models import (
    Item,
    ItemStatus,
    ItemVersion,
    JobRun,
    RawSnapshot,
    Source,
    SourceCursor,
)
from app.infrastructure.db.repositories.audit import AuditEventWriter
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.modules.acquisition.connectors import (
    DiscoveredEntry,
    decode_text,
    parse_feed,
    parse_releases,
    response_host,
)
from app.modules.acquisition.http import CollectionError, FetchResponse, SafeHttpClient, retry_time
from app.sources.config import GitHubSource, RssSource, SourceConfig

SOURCE_ADAPTER: TypeAdapter[SourceConfig] = TypeAdapter(SourceConfig)
HttpFactory = Callable[[SourceConfig], SafeHttpClient]


@dataclass(frozen=True)
class CollectionResult:
    source_key: str
    status: str
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    snapshots: int = 0
    error_code: str | None = None
    next_run_at: datetime | None = None


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def source_config(row: Source) -> SourceConfig:
    raw = {
        **row.config,
        "key": row.key,
        "name": row.name,
        "type": row.type.value,
        "enabled": row.enabled,
    }
    legal = dict(raw.get("legal", {}))
    legal.update(
        {
            "status": row.legal_status.value,
            "terms_url": row.terms_url,
            "terms_reviewed_at": row.terms_checked_at,
        }
    )
    raw["legal"] = legal
    try:
        return SOURCE_ADAPTER.validate_python(raw)
    except ValidationError:
        raise CollectionError("SOURCE_CONFIG_INVALID_RESYNC_REQUIRED") from None


def build_http(config: SourceConfig) -> SafeHttpClient:
    if isinstance(config, RssSource):
        hosts = config.allowed_hosts or [response_host(config.url)]
    else:
        hosts = ["api.github.com"]
    return SafeHttpClient(
        allowed_hosts=hosts,
        user_agent=config.user_agent or "CompanyNewsBot/1.0",
        timeout_seconds=config.timeout_seconds or 20,
        max_response_bytes=config.max_response_bytes or 5_242_880,
        min_delay_seconds=config.min_delay_seconds,
    )


def store_snapshot(session: Session, source_id: UUID, response: FetchResponse) -> RawSnapshot:
    try:
        body_text = decode_text(response)
    except CollectionError:
        body_text = response.body.decode("utf-8", errors="replace")
    snapshot = RawSnapshot(
        source_id=source_id,
        requested_url=response.requested_url,
        final_url=response.final_url,
        status_code=response.status_code,
        response_headers=response.headers,
        content_type=response.headers.get("content-type", ""),
        body_sha256=hashlib.sha256(response.body).hexdigest(),
        body_text=body_text if response.status_code != 304 else None,
        fetched_at=response.fetched_at,
        retention_until=response.fetched_at.date() + timedelta(days=365),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def next_link(response: FetchResponse, cached: dict[str, Any]) -> str | None:
    link = response.headers.get("link")
    if link is None:
        return cached.get("next_url") if response.status_code == 304 else None
    links = httpx.Response(200, headers={"Link": link}).links
    return links.get("next", {}).get("url")


def upsert_entry(
    session: Session,
    source_id: UUID,
    entry: DiscoveredEntry,
    snapshot: RawSnapshot | None,
    *,
    dry_run: bool,
) -> str:
    item = session.scalar(
        select(Item).where(
            Item.source_id == source_id,
            Item.external_id == entry.external_id,
        )
    )
    if item is None:
        duplicate = session.scalar(
            select(Item).where(
                Item.source_id == source_id,
                Item.canonical_url == entry.canonical_url,
                Item.content_sha256 == entry.content_sha256,
            )
        )
        if duplicate is not None:
            return "unchanged"
    elif item.content_sha256 == entry.content_sha256:
        return "unchanged"
    action = "created" if item is None else "updated"
    if dry_run:
        return action
    assert snapshot is not None
    if item is None:
        item = Item(source_id=source_id, external_id=entry.external_id, version=1)
        session.add(item)
    else:
        item.version += 1
    item.canonical_url = entry.canonical_url
    item.title_original = entry.title
    item.content_text = entry.content
    item.content_sha256 = entry.content_sha256
    item.published_at = entry.published_at
    item.language = entry.language
    item.status = ItemStatus.FETCHED
    session.flush()
    session.add(
        ItemVersion(
            item_id=item.id,
            version_no=item.version,
            snapshot_id=snapshot.id,
            title=entry.title,
            content_text=entry.content,
            content_sha256=entry.content_sha256,
            published_at=entry.published_at,
            observed_at=snapshot.fetched_at,
        )
    )
    session.flush()
    return action


def collect_source(
    session: Session,
    key: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    http_factory: HttpFactory = build_http,
    now: datetime | None = None,
    github_token: str | None = None,
) -> CollectionResult:
    current = now or datetime.now(UTC)
    statement = select(Source).where(Source.key == key)
    if not dry_run:
        statement = statement.with_for_update()
    source = session.scalar(statement)
    if source is None:
        return CollectionResult(key, "blocked", error_code="SOURCE_NOT_FOUND")
    try:
        config = source_config(source)
        config.assert_collectable(current)
    except PermissionError:
        return CollectionResult(key, "blocked", error_code="LEGAL_GATE_BLOCKED")
    except CollectionError as exc:
        return CollectionResult(key, "blocked", error_code=exc.code)
    if not isinstance(config, (RssSource, GitHubSource)):
        return CollectionResult(key, "blocked", error_code="UNSUPPORTED_SOURCE_TYPE")
    previous_job = session.scalar(
        select(JobRun)
        .where(
            JobRun.source_id == source.id,
        )
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    rate_limited = previous_job is not None and previous_job.error_code == "RATE_LIMITED"
    if previous_job and previous_job.stats_json.get("not_before"):
        barrier = datetime.fromisoformat(previous_job.stats_json["not_before"])
        if utc(barrier) > current:
            return CollectionResult(key, "deferred", next_run_at=utc(barrier))
    if source.next_run_at and utc(source.next_run_at) > current and (not force or rate_limited):
        return CollectionResult(key, "deferred", next_run_at=utc(source.next_run_at))
    cursor = session.get(SourceCursor, source.id)
    config_hash = canonical_payload_hash(source.config)
    cache = (
        cursor.cursor_json
        if cursor and cursor.cursor_json.get("config_hash") == config_hash
        else {}
    )
    pages_cache: dict[str, Any] = cache.get("pages", {})
    next_pages: dict[str, Any] = {}
    job = None
    if not dry_run:
        job = JobRun(
            job_type="acquisition",
            source_id=source.id,
            scheduled_for=current,
            started_at=current,
            status="running",
            idempotency_key=f"acquisition:{source.id}:{uuid4()}",
        )
        session.add(job)
        session.flush()
    snapshots: list[RawSnapshot] = []
    decoded: list[tuple[DiscoveredEntry, RawSnapshot | None]] = []
    responses: list[FetchResponse] = []
    client = http_factory(config)
    next_run = current + timedelta(minutes=config.interval_minutes or 60)
    not_before: datetime | None = None
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    try:
        url = (
            config.url
            if isinstance(config, RssSource)
            else (f"https://api.github.com/repos/{config.repository}/releases?per_page=100")
        )
        page_limit = 1 if isinstance(config, RssSource) else config.max_pages_per_run
        total_bytes = 0
        visited: set[str] = set()
        for _ in range(page_limit):
            if url in visited:
                raise CollectionError("PAGINATION_LOOP")
            visited.add(url)
            saved = pages_cache.get(url, {})
            headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml"}
            if isinstance(config, GitHubSource):
                headers = {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                }
                if github_token:
                    headers["Authorization"] = f"Bearer {github_token}"
            response = client.get(
                url,
                etag=saved.get("etag"),
                last_modified=saved.get("last_modified"),
                headers=headers,
            )
            if response.status_code == 304 and not saved:
                raise CollectionError("UNEXPECTED_NOT_MODIFIED")
            responses.append(response)
            snapshot = None if dry_run else store_snapshot(session, source.id, response)
            if snapshot:
                snapshots.append(snapshot)
            total_bytes += len(response.body)
            if total_bytes > (config.max_response_bytes or 5_242_880):
                raise CollectionError("RUN_TOO_LARGE")
            retry_at = retry_time(response.headers, current)
            if retry_at:
                next_run = max(next_run, retry_at)
                not_before = max(not_before or current, retry_at)
            try:
                next_run = max(
                    next_run,
                    current + timedelta(seconds=int(response.headers.get("x-poll-interval", "0"))),
                )
            except (ValueError, OverflowError):
                pass
            if response.status_code == 200:
                entries = (
                    parse_feed(response, config, config.language_hint)
                    if isinstance(config, RssSource)
                    else parse_releases(response, config, config.language_hint)
                )
                decoded.extend((entry, snapshot) for entry in entries)
            following = next_link(response, saved) if isinstance(config, GitHubSource) else None
            if following and isinstance(config, GitHubSource):
                parsed_next = client.policy.validate(following)
                expected_path = f"/repos/{config.repository}/releases".casefold()
                if parsed_next.path.casefold() != expected_path:
                    raise CollectionError("PAGINATION_URL_BLOCKED")
                following = str(parsed_next)
            next_pages[url] = {
                "etag": response.headers.get("etag", saved.get("etag"))
                if response.status_code == 304
                else response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified", saved.get("last_modified"))
                if response.status_code == 304
                else response.headers.get("last-modified"),
                "next_url": following,
            }
            if not following:
                break
            if retry_at and retry_at > current:
                raise CollectionError("RATE_LIMITED", retry_at=retry_at)
            url = following
        else:
            raise CollectionError("PAGE_LIMIT")
        seen: dict[str, str] = {}
        for entry, _ in decoded:
            if entry.external_id in seen and seen[entry.external_id] != entry.content_sha256:
                raise CollectionError("CONFLICTING_ENTRY_ID")
            seen[entry.external_id] = entry.content_sha256
        # Decode every page before mutating items. A savepoint also makes persistence atomic.
        with session.begin_nested():
            changed_snapshots: dict[UUID, RawSnapshot] = {}
            processed: set[str] = set()
            for entry, snapshot in decoded:
                if entry.external_id in processed:
                    continue
                processed.add(entry.external_id)
                action = upsert_entry(session, source.id, entry, snapshot, dry_run=dry_run)
                counts[action] += 1
                if action != "unchanged" and snapshot:
                    changed_snapshots[snapshot.id] = snapshot
            if not dry_run:
                for snapshot in changed_snapshots.values():
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
                        producer_version="0.1.0",
                        correlation_id=job.id if job else None,
                    )
                    ModuleMessageRepository(session).enqueue_once(envelope, consumer="extraction")
                if cursor is None:
                    cursor = SourceCursor(source_id=source.id)
                    session.add(cursor)
                first = next(iter(next_pages.values()))
                cursor.etag, cursor.last_modified = first["etag"], first["last_modified"]
                cursor.cursor_json = {"config_hash": config_hash, "pages": next_pages}
                if decoded:
                    cursor.last_external_id = decoded[-1][0].external_id
                source.last_success_at, source.next_run_at = current, next_run
        status = (
            "dry_run"
            if dry_run
            else (
                "not_modified"
                if all(response.status_code == 304 for response in responses)
                else "success"
            )
        )
        if job:
            job.status, job.finished_at = status, datetime.now(UTC)
            job.stats_json = {
                **counts,
                "not_before": not_before.isoformat() if not_before else None,
            }
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
            key,
            status,
            created=counts["created"],
            updated=counts["updated"],
            unchanged=counts["unchanged"],
            snapshots=len(responses),
            next_run_at=next_run,
        )
    except CollectionError as exc:
        if job:
            job.status, job.finished_at = "failed", datetime.now(UTC)
            job.error_code, job.error_message = exc.code, exc.code
            job.stats_json = {"snapshots": len(snapshots)}
            source.next_run_at = max(next_run, exc.retry_at or current)
            AuditEventWriter(session).append(
                actor_type="system",
                actor_id="acquisition",
                action="source.collection_failed",
                entity_type="source",
                entity_id=str(source.id),
                trace_id=str(job.id),
                after={"error_code": exc.code, "snapshots": len(snapshots)},
            )
        return CollectionResult(
            key,
            "failed",
            snapshots=len(responses),
            error_code=exc.code,
            next_run_at=max(next_run, exc.retry_at or current),
        )
    finally:
        client.close()
