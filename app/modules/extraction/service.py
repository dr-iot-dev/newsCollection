"""Deterministic static-document extraction; page contents never execute or instruct."""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.contracts.content_v1 import NormalizedContentV1
from app.core.content import normalize_text, normalize_url
from app.sources.config import WebSelectors

BOILERPLATE = (
    "script, style, noscript, nav, footer, header, aside, iframe, object, embed, form, "
    "[hidden], [aria-hidden=true], [role=banner], [role=navigation], [role=dialog], "
    ".cookie-banner, #cookie-banner, .cookie-consent, .advertisement"
)
BLOCKS = {
    "p",
    "div",
    "section",
    "article",
    "h1",
    "h2",
    "h3",
    "h4",
    "li",
    "ul",
    "ol",
    "br",
    "blockquote",
    "pre",
    "tr",
}


def visible_text(node: Tag) -> str:
    copy = BeautifulSoup(str(node), "html.parser")
    for unwanted in copy.select(BOILERPLATE):
        unwanted.decompose()
    for block in copy.find_all(BLOCKS):
        block.insert_before("\n")
        block.insert_after("\n")
    return normalize_text(copy.get_text("", strip=False))


def article_data(document: BeautifulSoup) -> dict[str, Any]:
    pending: list[Any] = []
    for script in document.select('script[type="application/ld+json"]')[:20]:
        try:
            pending.append(json.loads(script.get_text()))
        except (ValueError, RecursionError):
            continue
    steps = 0
    while pending and steps < 2000:
        steps += 1
        value = pending.pop(0)
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict):
            kind = value.get("@type", [])
            kinds = [kind] if isinstance(kind, str) else kind
            if isinstance(kinds, list) and any(
                k in {"NewsArticle", "Article", "BlogPosting"} for k in kinds if isinstance(k, str)
            ):
                return value
            if "@graph" in value:
                pending.append(value["@graph"])
    return {}


def parse_date(
    value: str | None, timezone_hint: str | None = None
) -> tuple[datetime | None, date | None, str]:
    if not value:
        return None, None, "unknown"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            return None, date.fromisoformat(value.strip()), "date"
        timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if timestamp.tzinfo is None and timezone_hint:
            timestamp = timestamp.replace(tzinfo=ZoneInfo(timezone_hint))
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(UTC)
            return timestamp, timestamp.date(), "second"
    except ValueError:
        pass
    return None, None, "unknown"


def extract_content(
    *,
    item_id: UUID,
    item_version: int,
    snapshot_id: UUID,
    url: str,
    title: str,
    body: str,
    published_at: datetime | None,
    language: str,
    is_html: bool,
    selectors: WebSelectors | None = None,
    allowed_hosts: list[str] | None = None,
    timezone_hint: str | None = None,
) -> NormalizedContentV1:
    reasons: list[str] = [f"source_timezone:{timezone_hint}"] if timezone_hint else []
    canonical = normalize_url(url)
    metadata: dict[str, Any] = {}
    method = "provided_text"
    title_match = False
    selector_match = False
    ratio_good = True
    clean_good = True
    date_value: str | None = None
    modified: datetime | None = None
    language_source, confidence = "source_hint", 0.8 if language != "und" else 0.0
    if is_html:
        document = BeautifulSoup(body, "html.parser")
        metadata = article_data(document)

        def meta(key: str) -> str | None:
            node = document.find("meta", attrs={"property": key}) or document.find(
                "meta", attrs={"name": key}
            )
            value = node.get("content") if isinstance(node, Tag) else None
            return value if isinstance(value, str) else None

        title_node = document.select_one(selectors.title) if selectors else None
        heading = document.select_one("h1")
        ld_title = metadata.get("headline")
        ld_title = ld_title if isinstance(ld_title, str) else None
        title = (
            (title_node.get_text(" ", strip=True) if title_node else None)
            or ld_title
            or meta("og:title")
            or (heading.get_text(" ", strip=True) if heading else None)
            or title
        )
        title_match = bool(
            ld_title and normalize_text(ld_title).casefold() == normalize_text(title).casefold()
        )
        canonical_node = document.select_one('link[rel~="canonical"]')
        href = canonical_node.get("href") if canonical_node else None
        if isinstance(href, str):
            candidate = urljoin(url, href)
            try:
                parsed = urlsplit(candidate)
                port = parsed.port
            except ValueError:
                parsed = urlsplit("https://invalid.example")
                port = -1
            allowed = allowed_hosts or [urlsplit(url).hostname or ""]
            if (
                parsed.scheme == "https"
                and parsed.hostname in allowed
                and parsed.username is None
                and port in (None, 443)
                and urlsplit(candidate).netloc.lower() == urlsplit(url).netloc.lower()
            ):
                canonical = normalize_url(candidate)
            else:
                reasons.append("canonical_rejected")
        published_node = document.select_one(selectors.published_at) if selectors else None
        if published_node:
            selector_value = published_node.get("datetime") or published_node.get_text(
                " ", strip=True
            )
            date_value = selector_value if isinstance(selector_value, str) else None
        if parse_date(date_value, timezone_hint)[1] is None:
            value = metadata.get("datePublished") or meta("article:published_time") or meta("date")
            date_value = value if isinstance(value, str) else None
        value = metadata.get("dateModified") or meta("article:modified_time")
        modified = parse_date(value if isinstance(value, str) else None, timezone_hint)[0]
        lang_node = document.find("html")
        lang_value = lang_node.get("lang") if isinstance(lang_node, Tag) else None
        lang_value = lang_value or meta("content-language") or metadata.get("inLanguage")
        if (
            isinstance(lang_value, str)
            and re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", lang_value)
            and len(lang_value) <= 10
        ):
            language, language_source, confidence = lang_value, "document_metadata", 0.95
        body_node = document.select_one(selectors.body) if selectors else None
        full_text = visible_text(document)
        if body_node:
            extracted = visible_text(body_node)
            method = "site_selector"
            selector_match = bool(title_node and published_node and extracted)
        elif isinstance(metadata.get("articleBody"), str):
            extracted = visible_text(BeautifulSoup(metadata["articleBody"], "html.parser"))
            method = "json_ld"
        else:
            body_node = document.select_one("article") or document.select_one("main")
            if body_node:
                extracted, method = visible_text(body_node), "semantic_html"
            else:
                sections = document.select("section, div")
                candidates = [node for node in sections if len(node.find_all("p")) >= 2]
                body_node = max(candidates, key=lambda node: len(node.get_text()), default=None)
                extracted = visible_text(body_node or document)
                method = "generic_dom" if body_node else "unstructured_html"
        body = extracted
        ratio = len(body) / max(1, len(full_text))
        ratio_good = 0.15 <= ratio <= 1.2
        clean_good = len(body) > 0 and not re.search(
            r"accept all cookies|cookie settings|all rights reserved", body, re.I
        )
    body, title = normalize_text(body), normalize_text(title)[:1000] or "Untitled"
    if language == "und" and re.search(r"[\u3040-\u30ff]", body):
        language, language_source, confidence = "ja", "script_heuristic", 0.6
    publication_date: date | None
    if published_at is not None:
        published_at = (
            published_at.replace(tzinfo=UTC)
            if published_at.tzinfo is None
            else published_at.astimezone(UTC)
        )
        publication_date, precision = published_at.date(), "second"
    else:
        published_at, publication_date, precision = parse_date(date_value, timezone_hint)
    criteria = [
        ("title_present", title != "Untitled", 0.15),
        ("body_300_chars", len(body) >= 300, 0.25),
        ("published_date_present", publication_date is not None, 0.10),
        ("structured_title_matches", title_match, 0.15),
        ("body_ratio_valid", ratio_good, 0.15),
        ("low_boilerplate", clean_good, 0.10),
        ("configured_selectors_match", selector_match, 0.10),
    ]
    score = round(sum(weight for _, passed, weight in criteria if passed), 3)
    reasons.extend(name for name, passed, _ in criteria if passed)
    if not body or method == "unstructured_html":
        score = min(score, 0.55)
        reasons.append("extraction_requires_review")
    if len(body) < 300:
        score = min(score, 0.55)
        reasons.append("short_body_requires_review")
    return NormalizedContentV1(
        item_id=item_id,
        item_version=item_version,
        snapshot_id=snapshot_id,
        canonical_url=canonical,
        title=title,
        body=body,
        body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        published_at=published_at,
        published_date=publication_date,
        modified_at=modified,
        date_precision=precision,
        language=language[:10],
        language_confidence=confidence,
        language_source=language_source,
        extraction_method=method,
        quality_score=score,
        quality_reasons=tuple(reasons),
    )
