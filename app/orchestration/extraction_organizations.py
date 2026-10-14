"""Select the newest saved PR TIMES release independently for each company ID."""

import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

JST = timezone(timedelta(hours=9))
POLICY = "prtimes-company-id-latest-publication-v2"
RELEASE_PATH = re.compile(r"/main/html/rd/p/(\d+)\.(\d+)\.html")


class OfficialMetadata(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.company_ids: set[int] = set()
        self.in_json = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("type") == "application/ld+json":
            self.in_json = True
            self.parts = []
        if tag == "a":
            href = values.get("href") or ""
            parsed = urlsplit(href)
            if parsed.netloc and parsed.netloc != "prtimes.jp":
                return
            match = re.search(r"company_id(?:/|=)(\d+)", href)
            if match:
                self.company_ids.add(int(match[1]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_json:
            self.scripts.append("".join(self.parts))
            self.in_json = False

    def handle_data(self, data: str) -> None:
        if self.in_json:
            self.parts.append(data)


def publication_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=JST)
    return result.astimezone(UTC)


def article_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [node for item in value for node in article_nodes(item)]
    if not isinstance(value, dict):
        return []
    kinds = value.get("@type", [])
    if isinstance(kinds, str):
        kinds = [kinds]
    result = [value] if "NewsArticle" in kinds or "Article" in kinds else []
    return result + article_nodes(value.get("@graph", []))


def release_metadata(url: str, document: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    path = RELEASE_PATH.fullmatch(parsed.path)
    if parsed.hostname != "prtimes.jp" or path is None:
        raise ValueError("expected a PR TIMES release URL")
    parser = OfficialMetadata()
    parser.feed(document)
    release_id, company_id = (int(value) for value in path.groups())
    if company_id not in parser.company_ids:
        raise ValueError("official company link does not confirm the release organization")
    candidates = []
    for script in parser.scripts:
        try:
            nodes = article_nodes(json.loads(script))
        except json.JSONDecodeError:
            continue
        for node in nodes:
            author = node.get("author")
            published = node.get("datePublished")
            if not isinstance(author, dict) or not isinstance(published, str):
                continue
            name = author.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            kinds = author.get("@type", [])
            if isinstance(kinds, str):
                kinds = [kinds]
            if "Organization" not in kinds:
                continue
            candidates.append((name.strip(), publication_time(published)))
    unique = set(candidates)
    if len(unique) != 1:
        raise ValueError("missing or conflicting official publication/organization metadata")
    name, published = unique.pop()
    return {
        "organization_id": f"prtimes:{company_id:09d}",
        "organization_name": name,
        "organization_url": f"https://prtimes.jp/main/html/searchrlp/company_id/{company_id}",
        "release_id": release_id,
        "published_at": published.astimezone(JST).isoformat(),
        "published_at_utc": published.isoformat(),
        "metadata_basis": "official company link and NewsArticle.author/datePublished",
    }


def latest_articles(
    articles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len({a["article_id"] for a in articles}) != len(articles):
        raise ValueError("duplicate input article IDs")
    winners: dict[str, dict[str, Any]] = {}
    for article in articles:
        organization = article["organization_id"]
        if not isinstance(organization, str) or not organization:
            raise ValueError("missing publishing organization")
        order = (
            publication_time(article["published_at_utc"]),
            article["release_id"],
            article["article_id"],
        )
        previous = winners.get(organization)
        if previous is None or order > (
            publication_time(previous["published_at_utc"]),
            previous["release_id"],
            previous["article_id"],
        ):
            winners[organization] = article
    selected = [a for a in articles if winners[a["organization_id"]] is a]
    excluded = []
    for article in articles:
        kept = winners[article["organization_id"]]
        if kept is article:
            continue
        row = {k: v for k, v in article.items() if k != "value"}
        row.update(
            selected_f_id=kept["f_id"],
            selected_article_id=kept["article_id"],
            reason="same_prtimes_company_id; older_publication_or_timestamp_tie",
        )
        excluded.append(row)
    return selected, excluded


def canonical_organizations(
    articles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep publishing IDs distinct; the legacy function name is retained for callers.

    A shared official name does not establish that two publishing accounts cover
    the same field. Restore the original ID when handling previously annotated rows.
    """
    rows = []
    for article in articles:
        company_id = article.get("publishing_organization_id", article["organization_id"])
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("missing publishing company ID")
        rows.append(
            {
                **article,
                "publishing_organization_id": company_id,
                "organization_id": company_id,
            }
        )
    return rows, []


def select_latest_organizations(source: Path, audit_database: Path, output: Path) -> Path:
    source_bytes = source.read_bytes()
    payload = json.loads(source_bytes.decode("utf-8-sig"))
    urls = {a["url"] for a in payload["articles"]}
    filename = audit_database.resolve().as_posix()
    uri = "file:" + ("//" if filename.startswith("//") else "") + quote(filename, safe="/:")
    metadata: dict[str, dict[str, Any]] = {}
    fetched: dict[str, str] = {}
    with sqlite3.connect(uri + "?mode=ro", uri=True) as db:
        db.execute("CREATE TEMP TABLE wanted_urls (url TEXT PRIMARY KEY)")
        db.executemany("INSERT INTO wanted_urls VALUES (?)", [(url,) for url in urls])
        for url, document, digest, checked_at in db.execute(
            "SELECT final_url,body_text,body_sha256,fetched_at FROM raw_snapshots "
            "WHERE final_url IN (SELECT url FROM wanted_urls)"
        ):
            if url in fetched and checked_at <= fetched[url]:
                continue
            details = release_metadata(url, document)
            details.update(source_snapshot_hash=digest, metadata_checked_at=checked_at)
            metadata[url] = details
            fetched[url] = checked_at
    if urls - metadata.keys():
        raise ValueError(f"official metadata missing for {len(urls - metadata.keys())} articles")
    annotated = [{**a, **metadata[a["url"]]} for a in payload["articles"]]
    annotated, merged = canonical_organizations(annotated)
    selected, excluded = latest_articles(annotated)
    distribution = Counter(a["organization_id"] for a in annotated)
    summary = {
        "policy": POLICY,
        "source_file": str(source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "audit_database": str(audit_database),
        "source_article_count": len(annotated),
        "selected_article_count": len(selected),
        "removed_article_count": len(excluded),
        "organization_count": len(distribution),
        "official_company_id_count": len({a["publishing_organization_id"] for a in annotated}),
        "same_official_name_company_id_merges": merged,
        "identity_basis": "PR TIMES company ID; never merge distinct IDs by official name",
        "organizations_with_multiple_articles": sum(n > 1 for n in distribution.values()),
        "latest_basis": "datePublished; not dateModified",
        "timestamp_without_timezone": "Asia/Tokyo (UTC+09:00)",
        "timestamp_tie_break": "descending numeric release_id, then article_id",
        "embedding_API_requests": 0,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    cohort = {**payload.get("cohort", {}), "organization_filter": summary}
    cohort.update(source_F_count=len(annotated), F_count=len(selected))
    filtered = {**payload, "articles": selected, "cohort": cohort}
    output.mkdir(parents=True, exist_ok=True)
    target = output / "article-values.json"
    for name, data in (
        ("article-values.json", filtered),
        ("organization-selection.json", summary),
        (
            "organization-metadata.json",
            [{k: v for k, v in a.items() if k != "value"} for a in annotated],
        ),
        ("organization-excluded.json", excluded),
    ):
        (output / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    for name, rows in (
        ("organization-selected.csv", selected),
        ("organization-excluded.csv", excluded),
    ):
        fields = ["f_id", "organization_id", "organization_name", "published_at", "title", "url"]
        if name == "organization-excluded.csv":
            fields += ["selected_f_id", "selected_article_id", "reason"]
        with (output / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    return target
