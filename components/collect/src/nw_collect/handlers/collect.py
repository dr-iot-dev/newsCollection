"""Bounded source collection from a supplied plan; no database."""

import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid5

from bs4 import BeautifulSoup
from pydantic import TypeAdapter

from nw_collect._vendor.modules.acquisition.connectors import decode_text, parse_feed, parse_releases
from nw_collect._vendor.modules.acquisition.http import SafeHttpClient
from nw_collect._vendor.modules.acquisition.robots import RobotsPolicy
from nw_collect._vendor.sources.config import GitHubSource, RssSource, SourceConfig, WebSource

from ..common import Context, Outcome, StageInput, output, required
from ..protocol import NAMESPACE, ProtocolError, digest, normalize_url


def run(inputs: dict[str, StageInput], parameters: dict[str, Any], context: Context) -> Outcome:
    plan = required(inputs, "plan").payload
    purpose = plan.get("purpose")
    if purpose not in {"scheduled", "explicit", "missing_sources"}:
        return Outcome.needs("FETCH_PURPOSE_REQUIRED")
    if purpose == "missing_sources" and not context.allow_fetch(parameters):
        return Outcome.needs("MISSING_SOURCE_FETCH_DISABLED")
    documents, assets = [], {}
    cursors: dict[str, dict[str, Any]] = {}
    specifications = plan.get("sources", [])
    if not specifications or len(specifications) > int(parameters.get("maximum_sources", 20)):
        return Outcome.needs("SOURCE_SPECIFICATIONS_REQUIRED")
    for specification in specifications:
        if purpose == "missing_sources" and not context.allow_fetch(parameters):
            return Outcome(
                "needs_input",
                issues=[{"code": "MISSING_SOURCE_FETCH_DISABLED", "retryable": False}],
            )
        source: SourceConfig = TypeAdapter[SourceConfig](SourceConfig).validate_python(
            specification
        )
        source.assert_collectable()
        if isinstance(source, GitHubSource):
            hosts = ["api.github.com", "github.com"]
        elif isinstance(source, RssSource):
            hosts = source.allowed_hosts or [urlsplit(source.url).hostname or ""]
        else:
            hosts = source.allowed_hosts
        client = SafeHttpClient(
            allowed_hosts=hosts,
            user_agent=source.user_agent or "NewsWeave/1.0 (+https://example.org)",
            timeout_seconds=source.timeout_seconds or 20,
            max_response_bytes=source.max_response_bytes or 5_242_880,
            min_delay_seconds=source.min_delay_seconds,
        )
        fetch = context.fetch or client.get
        try:
            if isinstance(source, WebSource):
                terms = fetch(source.legal.terms_url)
                terms_hash = digest(terms.body)
                baseline = plan.get("cursors", {}).get(source.key, {}).get("terms_hash")
                if baseline and baseline != terms_hash:
                    raise ProtocolError("SOURCE_TERMS_CHANGED")
                origin = "https://" + urlsplit(source.list_url).netloc
                robots_response = fetch(origin + "/robots.txt")
                robots = RobotsPolicy(
                    decode_text(robots_response), source.user_agent or "NewsWeave"
                )

                policy_source: WebSource = source

                def guard(
                    url: str,
                    policy_source: WebSource = policy_source,
                    robots: RobotsPolicy = robots,
                ) -> None:
                    if (
                        not any(
                            re.search(pattern, url) for pattern in policy_source.allow_url_patterns
                        )
                        or any(
                            re.search(pattern, url) for pattern in policy_source.deny_url_patterns
                        )
                        or not robots.allowed(url)
                    ):
                        raise ProtocolError("SOURCE_URL_NOT_PERMITTED")

                listing = fetch(source.list_url, url_guard=guard)
                page = BeautifulSoup(decode_text(listing), "html.parser")
                from urllib.parse import urljoin

                urls = plan.get("urls", []) or [
                    urljoin(source.list_url, href)
                    for href in (
                        node.get("href") for node in page.select(source.selectors.list_links)
                    )
                    if isinstance(href, str) and href
                ]
                for url in list(dict.fromkeys(urls))[
                    : min(
                        source.max_pages_per_run - 1, int(parameters.get("maximum_documents", 20))
                    )
                ]:
                    guard(url)
                    if purpose == "missing_sources" and not context.allow_fetch(parameters):
                        break
                    response = fetch(url, url_guard=guard)
                    name = "assets/" + digest(response.body)[7:] + ".html"
                    assets[name] = response.body
                    canonical = normalize_url(response.final_url)
                    documents.append(
                        {
                            "item_id": str(uuid5(NAMESPACE, canonical)),
                            "snapshot_id": str(uuid5(NAMESPACE, digest(response.body))),
                            "url": canonical,
                            "title": "",
                            "path": name,
                            "sha256": digest(response.body),
                            "published_at": None,
                            "fetched_at": response.fetched_at.isoformat(),
                            "language": source.language_hint or "ja",
                            "is_html": True,
                            "selectors": source.selectors.model_dump(),
                            "allowed_hosts": source.allowed_hosts,
                            "timezone_hint": source.timezone_hint,
                            "rights_approved": True,
                            "headers": {
                                "content-type": response.headers.get(
                                    "content-type", "text/html; charset=utf-8"
                                )
                            },
                            "source_key": source.key,
                        }
                    )
                cursors[source.key] = {"terms_hash": terms_hash}
            else:
                url = (
                    source.url
                    if isinstance(source, RssSource)
                    else ("https://api.github.com/repos/" + source.repository + "/releases")
                )
                response = fetch(url)
                entries = (
                    parse_feed(response, source, source.language_hint)
                    if isinstance(source, RssSource)
                    else parse_releases(response, source, source.language_hint)
                )
                for entry in entries[: int(parameters.get("maximum_documents", 20))]:
                    raw = entry.content.encode()
                    name = "assets/" + digest(raw)[7:] + ".txt"
                    assets[name] = raw
                    canonical = normalize_url(entry.canonical_url)
                    documents.append(
                        {
                            "item_id": str(uuid5(NAMESPACE, canonical)),
                            "snapshot_id": str(uuid5(NAMESPACE, digest(raw))),
                            "url": canonical,
                            "title": entry.title,
                            "path": name,
                            "sha256": digest(raw),
                            "published_at": entry.published_at.isoformat()
                            if entry.published_at
                            else None,
                            "fetched_at": response.fetched_at.isoformat(),
                            "language": entry.language,
                            "is_html": False,
                            "allowed_hosts": hosts,
                            "rights_approved": True,
                            "source_key": source.key,
                        }
                    )
                cursors[source.key] = {
                    key: response.headers.get(key) for key in ("etag", "last-modified")
                }
        finally:
            client.close()
    return output(
        "sources",
        "SourceBatchV1",
        {"documents": documents, "cursors": cursors, "purpose": purpose},
        assets,
    )
