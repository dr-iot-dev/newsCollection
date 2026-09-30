"""Feed and release decoding. No HTML rendering, asset download, or article crawling."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin
from xml.etree.ElementTree import Element, ParseError, tostring

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.contracts.envelope import canonical_payload_hash
from app.modules.acquisition.http import CollectionError, FetchResponse, URLPolicy
from app.sources.config import GitHubSource, RssSource

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


@dataclass(frozen=True)
class DiscoveredEntry:
    external_id: str
    canonical_url: str
    title: str
    content: str
    published_at: datetime | None
    language: str = "und"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_sha256(self) -> str:
        # Include title/date/release metadata so metadata-only corrections create a version.
        return canonical_payload_hash(
            {
                "url": self.canonical_url,
                "title": self.title,
                "content": self.content,
                "published_at": self.published_at.isoformat() if self.published_at else None,
                "language": self.language,
                "metadata": self.metadata,
            }
        ).removeprefix("sha256:")


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.rsplit(":", 1)[-1]
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self.blocked += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3"} and not self.blocked:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.rsplit(":", 1)[-1]
        if tag in {"script", "style", "iframe", "object", "embed"} and self.blocked:
            self.blocked -= 1
        elif tag in {"p", "div", "li"} and not self.blocked:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.blocked:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


def parse_date(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    # An unknown offset is not enough evidence to assert a publication time.
    return result.astimezone(UTC) if result.tzinfo is not None else None


def element_text(parent: Element, name: str) -> str:
    child = parent.find(name)
    return "" if child is None else "".join(child.itertext()).strip()


def element_html(parent: Element, name: str) -> str:
    child = parent.find(name)
    if child is None:
        return ""
    if len(child) == 0:
        return child.text or ""
    return (child.text or "") + "".join(tostring(node, encoding="unicode") for node in child)


def decode_text(response: FetchResponse) -> str:
    content_type = response.headers.get("content-type", "")
    encoding = "utf-8"
    declaration = re.match(rb"\s*<\?xml[^>]*encoding=[\x22\x27]([^\x22\x27]+)", response.body[:256])
    if declaration:
        try:
            encoding = declaration[1].decode("ascii")
        except UnicodeDecodeError:
            raise CollectionError("INVALID_ENCODING") from None
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset":
            encoding = value.strip("\"'")
    try:
        return response.body.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        raise CollectionError("INVALID_ENCODING") from None


def parse_feed(
    response: FetchResponse,
    source: RssSource,
    language: str | None,
) -> list[DiscoveredEntry]:
    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime not in {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}:
        raise CollectionError("INVALID_CONTENT_TYPE")
    # XML declarations are decoded by the hardened parser; HTTP charset is checked as well.
    if "charset=" in response.headers.get("content-type", "").lower():
        decode_text(response)
    try:
        root = ElementTree.fromstring(response.body, forbid_dtd=True)
    except (ParseError, DefusedXmlException, ValueError):
        raise CollectionError("PARSE_ERROR") from None
    atom = root.tag == f"{ATOM}feed"
    if not atom and root.tag != "rss":
        raise CollectionError("UNSUPPORTED_FEED")
    channel = root.find("channel") if not atom else root
    if channel is None:
        raise CollectionError("PARSE_ERROR")
    entries = channel.findall(f"{ATOM}entry" if atom else "item")
    if len(entries) > 10000:
        raise CollectionError("ITEM_LIMIT")
    policy = URLPolicy(source.allowed_hosts or [response_host(source.url)])
    result: list[DiscoveredEntry] = []
    entry_language = (
        language
        or root.get("{http://www.w3.org/XML/1998/namespace}lang")
        or (element_text(channel, "language") or "und")
    )
    if len(entry_language) > 10:
        raise CollectionError("INVALID_LANGUAGE")
    for node in entries:
        prefix = ATOM if atom else ""
        title = plain_text(element_text(node, f"{prefix}title"))
        if not title:
            raise CollectionError("ENTRY_MISSING_TITLE")
        if atom:
            link = next(
                (
                    child.get("href", "")
                    for child in node.findall(f"{ATOM}link")
                    if child.get("rel", "alternate") == "alternate"
                    and child.get("type", "text/html") in {"text/html", "application/xhtml+xml"}
                ),
                "",
            )
            external_id = element_text(node, f"{ATOM}id")
            published = element_text(node, f"{ATOM}published")
            content = element_html(node, f"{ATOM}content") or element_html(node, f"{ATOM}summary")
        else:
            link = element_text(node, "link")
            external_id = element_text(node, "guid")
            published = element_text(node, "pubDate")
            content = element_html(node, f"{CONTENT}encoded") or element_html(node, "description")
        fallback = hashlib.sha256(f"{title}\n{published}\n{link}".encode()).hexdigest()
        canonical = (
            str(policy.validate(urljoin(response.final_url, link)))
            if link
            else (str(policy.validate(source.url)).split("?", 1)[0] + f"?entry={fallback}")
        )
        external_id = external_id or (canonical if link else f"sha256:{fallback}")
        if len(external_id) > 4096:
            raise CollectionError("ENTRY_ID_TOO_LONG")
        result.append(
            DiscoveredEntry(
                external_id,
                canonical,
                title,
                plain_text(content),
                parse_date(published),
                entry_language,
                {"updated_at": element_text(node, f"{ATOM}updated")} if atom else {},
            )
        )
    return result


def response_host(value: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(value).hostname or ""


def parse_releases(
    response: FetchResponse,
    source: GitHubSource,
    language: str | None,
) -> list[DiscoveredEntry]:
    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime not in {"application/json", "application/vnd.github+json"}:
        raise CollectionError("INVALID_CONTENT_TYPE")
    try:
        releases = json.loads(decode_text(response))
    except (ValueError, RecursionError):
        raise CollectionError("PARSE_ERROR") from None
    if not isinstance(releases, list) or len(releases) > 100:
        raise CollectionError("PARSE_ERROR")
    result: list[DiscoveredEntry] = []
    policy = URLPolicy(["github.com"])
    for release in releases:
        if not isinstance(release, dict):
            raise CollectionError("PARSE_ERROR")
        if any(type(release.get(flag)) is not bool for flag in ("draft", "prerelease")):
            raise CollectionError("PARSE_ERROR")
        if (release["draft"] and not source.include_drafts) or (
            release["prerelease"] and not source.include_prereleases
        ):
            continue
        if type(release.get("id")) is not int or release["id"] <= 0:
            raise CollectionError("PARSE_ERROR")
        if any(
            release.get(key) is not None and not isinstance(release[key], str)
            for key in ("published_at", "updated_at", "tag_name")
        ):
            raise CollectionError("PARSE_ERROR")
        canonical = release.get("html_url")
        if not isinstance(canonical, str):
            raise CollectionError("PARSE_ERROR")
        canonical = str(policy.validate(canonical))
        if not canonical.casefold().startswith(
            f"https://github.com/{source.repository}/releases/".casefold()
        ):
            raise CollectionError("URL_BLOCKED")
        title = release.get("name") or release.get("tag_name")
        content = release.get("body") or ""
        if not isinstance(title, str) or not title or not isinstance(content, str):
            raise CollectionError("PARSE_ERROR")
        # Metadata remains in the raw JSON; never follow asset URLs.
        metadata = {
            key: release.get(key) for key in ("tag_name", "updated_at", "draft", "prerelease")
        }
        result.append(
            DiscoveredEntry(
                str(release["id"]),
                canonical,
                title,
                content,
                parse_date(release.get("published_at")),
                language or "und",
                metadata,
            )
        )
    return result
