"""Deterministic rendering and allowlist sanitization; no CMS or DB access."""

import hashlib
from html import escape
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, Tag
from markdown_it import MarkdownIt

from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.envelope import canonical_payload_hash
from app.contracts.wordpress_v1 import WordPressPayloadV1
from app.core.editorial import EditorialError

ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "h2",
        "h3",
        "h4",
        "ul",
        "ol",
        "li",
        "strong",
        "em",
        "a",
        "blockquote",
        "pre",
        "code",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
    }
)
DROP_TAGS = frozenset(
    {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "svg",
        "math",
        "form",
        "input",
        "button",
        "textarea",
        "select",
        "img",
        "video",
        "audio",
    }
)


def safe_link(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (
            url.scheme == "https"
            and bool(url.hostname)
            and url.username is None
            and url.password is None
            and not any(ord(c) <= 32 for c in value)
        )
    except ValueError:
        return False


def sanitize_html(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for node in list(soup.find_all(True)):
        if not isinstance(node, Tag) or node.name is None or node.parent is None:
            continue
        if node.name in DROP_TAGS:
            node.decompose()
        elif node.name not in ALLOWED_TAGS:
            node.unwrap()
        else:
            href = node.get("href") if node.name == "a" else None
            node.attrs = {}
            if isinstance(href, str) and safe_link(href):
                node["href"] = href
                node["rel"] = "noopener noreferrer"
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    return str(soup)


def plain_text(value: str) -> str:
    return BeautifulSoup(value, "html.parser").get_text()


def idempotency_key(target: str, item_id: object, revision: int) -> str:
    return hashlib.sha256(f"{target}|{item_id}|{revision}".encode()).hexdigest()


def normalize_source_section(value: str, urls: list[str]) -> str:
    """Replace draft source sections with one canonical, linked source list."""
    urls = sorted(set(urls))
    if not urls or any(not safe_link(url) for url in urls):
        raise EditorialError("WORDPRESS_SOURCE_LINK_REQUIRED", 422)
    soup = BeautifulSoup(value, "html.parser")
    for heading in list(soup.find_all("h2", recursive=False)):
        if heading.get_text(strip=True) != "出典":
            continue
        sibling = heading.next_sibling
        heading.decompose()
        while sibling is not None:
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2"}:
                break
            following = sibling.next_sibling
            sibling.extract()
            sibling = following
    sources = (
        "<h2>出典</h2><ul>"
        + "".join(f'<li><a href="{escape(url, quote=True)}">{escape(url)}</a></li>' for url in urls)
        + "</ul>"
    )
    return sanitize_html(str(soup).rstrip() + "\n" + sources)


def build_payload(
    draft: ArticleDraftV1,
    package: ArticlePackageV1,
    target: str,
    category_map: dict[str, int],
    tag_map: dict[str, int],
) -> WordPressPayloadV1:
    if not draft.category_keys or any(k not in category_map for k in draft.category_keys):
        raise EditorialError("WORDPRESS_CATEGORY_MAPPING_REQUIRED", 422)
    if any(t not in tag_map for t in draft.tags):
        raise EditorialError("WORDPRESS_TAG_MAPPING_REQUIRED", 422)
    urls = [str(ref.url) for ref in package.source_references if ref.url is not None]
    rendered = (
        MarkdownIt("commonmark", {"html": False})
        .enable("table")
        .render(draft.lead + "\n\n" + draft.body_markdown)
    )
    return WordPressPayloadV1(
        title=plain_text(draft.title),
        content=normalize_source_section(rendered, urls),
        excerpt=plain_text(draft.lead),
        slug="news-" + idempotency_key(target, draft.item_id, draft.revision),
        categories=tuple(sorted({category_map[k] for k in draft.category_keys})),
        tags=tuple(sorted({tag_map[t] for t in draft.tags})),
    )


def remote_payload(post: dict[str, Any]) -> dict[str, Any]:
    try:
        result = {key: post[key]["raw"] for key in ("title", "content", "excerpt")}
        if not all(isinstance(v, str) for v in result.values()):
            raise ValueError
        media = post.get("featured_media", 0)
        if type(media) is not int or media < 0:
            raise ValueError
        if media:
            result["featured_media"] = media
        result.update(
            slug=post["slug"],
            status=post["status"],
            categories=sorted(post["categories"]),
            tags=sorted(post["tags"]),
        )
        return result
    except (KeyError, TypeError, ValueError):
        raise EditorialError("WORDPRESS_RESPONSE_INVALID", 502) from None


def remote_hash(post: dict[str, Any]) -> str:
    return canonical_payload_hash(
        {**remote_payload(post), "modified_gmt": post.get("modified_gmt")}
    )


def matches_payload(post: dict[str, Any], payload: dict[str, Any], status: str) -> bool:
    return remote_payload(post) == {**payload, "status": status}
