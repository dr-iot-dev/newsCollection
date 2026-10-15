"""Acquire eligible public PR TIMES releases without term counts or vocabulary discovery."""

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.http import CollectionError, SafeHttpClient
from app.models import Article
from app.robots import RobotsPolicy

RELEASE = re.compile(r"^/main/html/rd/p/(\d+)\.(\d+)\.html$")
TYPE = re.compile(r"^/main/html/searchrlp/release_type_id/(\d+)/?$")
JST = timezone(timedelta(hours=9))
TERMS = {
    "AI": (
        "AI",
        "人工知能",
        "機械学習",
        "深層学習",
        "ディープラーニング",
        "LLM",
        "大規模言語モデル",
        "AIoT",
        "artificial intelligence",
        "machine learning",
    ),
    "IoT": ("IoT", "Internet of Things", "モノのインターネット", "AIoT"),
}


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def title_excluded(title: str, exclusions: list[str]) -> bool:
    value = normalized(title)
    return any(normalized(word) in value for word in exclusions if word)


def domain_names(title: str, body: str) -> list[str]:
    lead = re.split(r"(?:会社概要|企業概要|会社情報|企業情報)", body[:1200], maxsplit=1)[0]
    text = normalized(title + "\n" + lead)
    domains = []
    for domain, terms in TERMS.items():
        for term in terms:
            value = re.escape(normalized(term))
            if term.isascii():
                value = r"(?<![a-z0-9])" + value + r"(?![a-z0-9])"
            if re.search(value, text):
                domains.append(domain)
                break
    return domains


def article_nodes(value):
    if isinstance(value, list):
        return [node for item in value for node in article_nodes(item)]
    if not isinstance(value, dict):
        return []
    kinds = value.get("@type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    own = [value] if any(kind in {"NewsArticle", "Article"} for kind in kinds) else []
    return own + article_nodes(value.get("@graph", []))


def parse_article(url: str, html: str, exclusions: list[str]) -> dict | None:
    parsed = urlsplit(url)
    match = RELEASE.fullmatch(parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "prtimes.jp" or not match:
        raise ValueError("INVALID_RELEASE_URL")
    release_id, company = match.groups()
    page = BeautifulSoup(html, "html.parser")
    types = set()
    for link in page.select("a[href*='/main/html/searchrlp/release_type_id/']"):
        kind = TYPE.fullmatch(str(link.get("href", "")))
        if kind and not link.find_parent(id="press-release-body"):
            types.add((kind.group(1).zfill(2), link.get_text(" ", strip=True)))
    if types != {("01", "商品サービス")}:
        return None
    company_ids = set()
    for link in page.select("a[href]"):
        target = urlsplit(urljoin(url, str(link["href"])))
        found = re.search(r"company_id(?:/|=)(\d+)", target.path + "?" + target.query)
        if target.netloc == "prtimes.jp" and found:
            company_ids.add(int(found.group(1)))
    if int(company) not in company_ids:
        raise ValueError("UNCONFIRMED_COMPANY_ID")
    metadata = []
    for script in page.select('script[type="application/ld+json"]'):
        try:
            nodes = article_nodes(json.loads(script.get_text()))
        except ValueError:
            continue
        for node in nodes:
            author = node.get("author", {})
            if isinstance(author, dict) and author.get("name") and node.get("datePublished"):
                try:
                    stamp = datetime.fromisoformat(node["datePublished"].replace("Z", "+00:00"))
                except ValueError:
                    continue
                stamp = (stamp if stamp.tzinfo else stamp.replace(tzinfo=JST)).astimezone(UTC)
                metadata.append((str(author["name"]), stamp.isoformat(), node.get("headline", "")))
    if len(set(metadata)) != 1:
        raise ValueError("MISSING_OR_CONFLICTING_PUBLICATION_METADATA")
    company_name, published_at, headline = metadata[0]
    heading = page.select_one("#press-release-title, h1")
    title = heading.get_text(" ", strip=True) if heading else headline
    if "\ufffd" in title or not title:
        og = page.select_one('meta[property="og:title"]')
        title = next(
            (x for x in (headline, og.get("content", "") if og else "") if x and "\ufffd" not in x),
            "",
        )
    if not title:
        raise ValueError("MISSING_OFFICIAL_TITLE")
    if title_excluded(title, exclusions):
        return None
    body_node = page.select_one("#press-release-body")
    if body_node is None:
        raise ValueError("MISSING_ARTICLE_BODY")
    for node in body_node.select("script, style, nav, footer, iframe, form, [hidden]"):
        node.decompose()
    body = body_node.get_text("\n", strip=True)
    domains = domain_names(title, body)
    if not body or not domains:
        return None
    data = {
        "url": "https://prtimes.jp" + parsed.path,
        "company_id": f"prtimes:{int(company):09d}",
        "company_name": company_name,
        "release_id": int(release_id),
        "published_at": published_at,
        "title": title,
        "body": body,
        "domains": domains,
        "release_type": "01",
    }
    data["snapshot_hash"] = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    data["raw_html"] = html
    return data


def save_article(session: Session, data: dict) -> Article:
    existing = session.scalar(
        select(Article).where(
            Article.url == data["url"],
            Article.snapshot_hash == data["snapshot_hash"],
        )
    )
    if existing:
        return existing
    article = Article(**data)
    session.add(article)
    session.flush()
    return article


class Collector:
    def __init__(self, exclusions: list[str], client=None):
        self.exclusions = exclusions
        self.client = client or SafeHttpClient(
            allowed_hosts=["prtimes.jp"],
            user_agent="NewsWeave/2.0",
            min_delay_seconds=3,
        )
        self.robots = None

    def close(self):
        self.client.close()

    def get(self, url: str):
        if self.robots is None:
            response = self.client.get("https://prtimes.jp/robots.txt")
            self.robots = RobotsPolicy(response.body.decode("utf-8"), "NewsWeave")
            self.client.min_delay_seconds = max(self.client.min_delay_seconds, self.robots.delay)

        def allowed(target):
            if not self.robots.allowed(target):
                raise CollectionError("ROBOTS_DISALLOWED")

        allowed(url)
        response = self.client.get(url, url_guard=allowed)
        if response.status_code != 200:
            raise CollectionError("HTTP_STATUS")
        return response

    def collect(self, session: Session, urls: list[str]) -> dict:
        accepted, excluded = 0, 0
        for url in dict.fromkeys(urls):
            response = self.get(url)
            data = parse_article(response.final_url, response.body.decode("utf-8"), self.exclusions)
            if data is None:
                excluded += 1
            else:
                save_article(session, data)
                session.commit()
                accepted += 1
        return {"accepted": accepted, "excluded": excluded}

    def search(self, pages: int) -> list[str]:
        urls = []
        for word in ("AI", "IoT"):
            for page in range(1, pages + 1):
                url = "https://prtimes.jp/api/keyword_search.php/search?" + urlencode(
                    {
                        "keyword": word,
                        "page": page,
                        "limit": 40,
                    }
                )
                payload = json.loads(self.get(url).body)
                data = payload["data"]
                if payload.get("status") != 200 or data.get("current_page") != page:
                    raise ValueError("SEARCH_RESPONSE_SCHEMA")
                rows = data["release_list"]
                if not isinstance(rows, list):
                    raise ValueError("SEARCH_RESPONSE_SCHEMA")
                for row in rows:
                    title = row.get("title", "")
                    link = row.get("release_url", "")
                    if not link:
                        link = (
                            "/main/html/rd/p/"
                            + str(row["release_id"]).zfill(9)
                            + "."
                            + str(row["company_id"]).zfill(9)
                            + ".html"
                        )
                    if link and not title_excluded(title, self.exclusions):
                        urls.append(urljoin("https://prtimes.jp", link))
                if not rows or page >= data["last_page"]:
                    break
        return list(dict.fromkeys(urls))


def exclusions_from(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.startswith("#")
    ]
