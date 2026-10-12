"""PR TIMES native search and release acquisition with existing source controls."""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit

from pydantic import AnyHttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.acquisition_v1 import AcquisitionResultV1
from app.contracts.comparison_pair_discovery_v3 import (
    ACQUISITION_POLICY,
    SEARCH_POLICY,
    SEARCH_RESULTS_PER_KEYWORD,
    CategoryKeywords,
    PairDocument,
)
from app.contracts.envelope import ContractEnvelope, canonical_payload_hash
from app.core.comparison_pair_discovery import (
    TITLE_EXCLUSION_TERMS,
    embedding_text,
    excluded_title_terms,
    keyword_match,
    norm,
)
from app.core.content import normalize_url
from app.core.editorial import INJECTION, EditorialError
from app.infrastructure.db.models import Item, Source, SourceCursor
from app.infrastructure.db.repositories.messages import ModuleMessageRepository
from app.modules.acquisition.connectors import DiscoveredEntry, decode_text
from app.modules.acquisition.http import CollectionError, FetchResponse
from app.modules.acquisition.service import build_http, source_config, store_snapshot, upsert_entry
from app.modules.acquisition.web import WebGuard, html, legal_gate, origin
from app.modules.extraction.service import extract_content
from app.orchestration.editorial import eligible
from app.sources.config import WebSource

RELEASE = re.compile(r"^https://prtimes\.jp/main/html/rd/p/[0-9]+\.[0-9]+\.html$")
SEARCH_PATH = "/main/action.php"
SEARCH_API_PATH = "/api/keyword_search.php/search"
SEARCH_PAGE_SIZE = 40
EMPTY_SEARCH_MESSAGE = "に合致するプレスリリースはありませんでした。"


def search_result_links(response: FetchResponse, query: str) -> tuple[str, ...]:
    if response.status_code == 200:
        return release_links(response)
    if response.status_code == 404:
        page = html(response)
        title = norm(page.title.get_text(" ", strip=True)) if page.title else ""
        text = norm(page.get_text(" ", strip=True))
        if (
            title == norm(query + "に関するプレスリリース・ニュースリリース")
            and re.search(r"検索結果\s*:\s*0\s*件", text)
            and norm(EMPTY_SEARCH_MESSAGE) in text
        ):
            return ()
    raise CollectionError("PAIR_SEARCH_NOT_FOUND_UNCONFIRMED")


def native_search_url(query: str) -> str:
    # Verified against PR TIMES' public common.js executeSearch on 2026-10-11.
    return (
        "https://prtimes.jp"
        + SEARCH_PATH
        + "?"
        + urlencode({"run": "html", "page": "searchkey", "search_word": query})
    )


def keyword_search_url(query: str, page: int) -> str:
    # Public search UI client, index-C6i5yuyd.js/site-name-n7Vfnabb.js (2026-10-11).
    return (
        "https://prtimes.jp"
        + SEARCH_API_PATH
        + "?"
        + urlencode({"keyword": query, "page": page, "limit": SEARCH_PAGE_SIZE})
    )


def keyword_search_results(response: FetchResponse, page: int) -> tuple[list[dict[str, str]], int]:
    """Parse the public search response, without accepting an error as zero results."""
    try:
        if response.status_code != 200:
            raise ValueError("HTTP status")
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if mime != "application/json":
            raise ValueError("Search response type")
        payload = json.loads(response.body)
        if payload["status"] != 200:
            raise ValueError("Search status")
        data = payload["data"]
        current, last, total, limit = (
            data["current_page"],
            data["last_page"],
            data["total"],
            data["limit"],
        )
        if (
            any(type(v) is not int for v in (current, last, total, limit))
            or current != page
            or last < 0
            or total < 0
            or limit != SEARCH_PAGE_SIZE
            or (total > 0 and last < current)
        ):
            raise ValueError("Page metadata")
        entries = data["release_list"]
        if not isinstance(entries, list) or len(entries) > SEARCH_PAGE_SIZE:
            raise ValueError("Result list")
        if (not entries and total > 0) or (entries and total < len(entries)):
            raise ValueError("Result total")
        results = []
        for entry in entries:
            company, release = entry["company_id"], entry["release_id"]
            title, path = entry["title"], entry["release_url"]
            if (
                type(company) is not int
                or type(release) is not int
                or company <= 0
                or release <= 0
                or not isinstance(title, str)
                or not title.strip()
                or "\x00" in title
                or not isinstance(path, str)
            ):
                raise ValueError("Result identity")
            url = normalize_url(urljoin("https://prtimes.jp", path))
            if not RELEASE.fullmatch(url):
                raise ValueError("Release URL")
            ids = urlsplit(url).path.rsplit("/", 1)[-1].removesuffix(".html").split(".")
            if [int(v) for v in ids] != [release, company]:
                raise ValueError("URL identity mismatch")
            results.append({"article_id": url, "url": url, "title": title[:1000]})
        return results, last
    except (ValueError, TypeError, KeyError, IndexError):
        raise CollectionError("PAIR_SEARCH_RESPONSE_INVALID") from None


def release_links(response: FetchResponse, selector: str = "a[href]") -> tuple[str, ...]:
    found: dict[str, None] = {}
    for anchor in html(response).select(selector):
        href = anchor.get("href")
        if isinstance(href, str):
            url = normalize_url(urljoin(response.final_url, href))
            if RELEASE.fullmatch(url):
                found[url] = None
    return tuple(found)


class PRTimesPairAcquisition:
    def __init__(
        self,
        session: Session,
        source_key: str,
        save: Callable[[dict[str, Any]], None],
        reserve: Callable[[], None],
        *,
        results_per_keyword: int = SEARCH_RESULTS_PER_KEYWORD,
    ) -> None:
        self.session, self.save, self.reserve = session, save, reserve
        if not 1 <= results_per_keyword <= SEARCH_RESULTS_PER_KEYWORD:
            raise ValueError("Invalid per-keyword result limit")
        self.results_per_keyword = results_per_keyword
        row = session.scalar(select(Source).where(Source.key == source_key))
        if row is None:
            raise EditorialError("PAIR_SOURCE_NOT_FOUND")
        config = source_config(row)
        if not isinstance(config, WebSource) or urlsplit(config.list_url).hostname != "prtimes.jp":
            raise EditorialError("PAIR_PRTIMES_SOURCE_REQUIRED")
        if not urlsplit(config.list_url).path.startswith("/topics/keywords/"):
            raise EditorialError("PAIR_KEYWORD_CATEGORY_REQUIRED")
        try:
            config.assert_collectable()
        except PermissionError:
            raise EditorialError("PAIR_SOURCE_RIGHTS_BLOCKED") from None
        self.source, self.config = row, config
        self.category = unquote(urlsplit(config.list_url).path.rsplit("/", 1)[-1])
        self.client = build_http(config)
        self.guard: WebGuard | None = None
        self.last_result: dict[str, Any] = {}

    def check_policy(self, progress: dict[str, Any]) -> None:
        if progress.get("acquisition_policy", ACQUISITION_POLICY) != ACQUISITION_POLICY or (
            any(
                key in progress
                for key in (
                    "initial_links",
                    "initial_documents",
                    "searches",
                    "keyword_results",
                    "article_keyword_counts",
                    "candidate_urls",
                    "accepted",
                )
            )
            and (
                progress.get("acquisition_policy") != ACQUISITION_POLICY
                or progress.get("title_exclusion_terms") != list(TITLE_EXCLUSION_TERMS)
            )
        ):
            raise CollectionError("PAIR_ACQUISITION_CHECKPOINT_INCOMPATIBLE")
        progress.update(
            acquisition_policy=ACQUISITION_POLICY,
            title_exclusion_terms=list(TITLE_EXCLUSION_TERMS),
            category_tag_required=False,
        )

    def close(self) -> None:
        self.client.close()

    def setup(self) -> None:
        if self.guard is None:
            # Two control-document requests. Every invocation rechecks source policy.
            self.reserve()
            self.reserve()
            robots, _ = legal_gate(
                self.session,
                self.source,
                self.config,
                self.client,
                self.session.get(SourceCursor, self.source.id),
                datetime.now(UTC),
                False,
            )
            self.guard = WebGuard(self.config, self.client, robots)

    def fetch(self, url: str, *, listing: bool = False, search: bool = False) -> FetchResponse:
        self.setup()
        assert self.guard is not None
        # Retain source page limits per invocation; resume starts the next batch.
        if self.guard.count >= self.config.max_pages_per_run:
            raise CollectionError("PAGE_LIMIT")
        self.reserve()
        if search:

            def search_guard(value: str) -> None:
                assert self.guard is not None
                parsed = urlsplit(str(self.client.policy.validate(value)))
                pairs = parse_qsl(parsed.query)
                params = dict(pairs)
                native = (
                    parsed.path == SEARCH_PATH
                    and params.get("run") == "html"
                    and params.get("page") == "searchkey"
                    and not set(params) - {"run", "page", "search_word"}
                )
                public_api = (
                    parsed.path == SEARCH_API_PATH
                    and set(params) == {"keyword", "page", "limit"}
                    and bool(params.get("keyword"))
                    and re.fullmatch(r"[1-9][0-9]*", params.get("page", "")) is not None
                    and params.get("limit") == str(SEARCH_PAGE_SIZE)
                )
                if (
                    origin(value) != "https://prtimes.jp"
                    or len(pairs) != len(params)
                    or not (native or public_api)
                    or parsed.path != urlsplit(url).path
                    or params != dict(parse_qsl(urlsplit(url).query))
                    or not self.guard.robots.allowed(value)
                    or any(re.search(pattern, value) for pattern in self.config.deny_url_patterns)
                ):
                    raise CollectionError("PAIR_SEARCH_URL_BLOCKED")
                self.guard.count += 1
                if self.guard.count > self.config.max_pages_per_run:
                    raise CollectionError("PAGE_LIMIT")

            response = self.client.get(url, url_guard=search_guard, allow_not_found=True)
        else:
            response = self.client.get(
                url, url_guard=partial(self.guard.request_guard, listing=listing)
            )
        if response.status_code != 200 and not (search and response.status_code == 404):
            raise CollectionError("PAIR_HTTP_STATUS")
        return response

    def document(self, url: str, proof: str | None) -> PairDocument | None:
        response = self.fetch(url)
        page = html(response)
        snapshot = store_snapshot(self.session, self.source.id, response)
        self.last_result = {"snapshot_id": str(snapshot.id), "final_url": response.final_url}
        title_node = page.select_one(self.config.selectors.title) or page.select_one("h1")
        if title_node is None:
            raise CollectionError("PAIR_TITLE_MISSING")
        title = title_node.get_text(" ", strip=True)
        excluded = excluded_title_terms(title)
        self.last_result.update(title=title, title_exclusion_terms=list(excluded))
        if excluded:
            self.last_result["rejection"] = "title_excluded"
            return None
        entry = DiscoveredEntry(
            external_id=normalize_url(url),
            canonical_url=normalize_url(response.final_url),
            title=title[:1000],
            content=decode_text(response),
            published_at=None,
            language=self.config.language_hint or "und",
            metadata={"format": "html"},
        )
        self.session.scalar(select(Source).where(Source.id == self.source.id).with_for_update())
        action = upsert_entry(self.session, self.source.id, entry, snapshot, dry_run=False)
        item = self.session.scalar(
            select(Item).where(
                Item.source_id == self.source.id, Item.external_id == entry.external_id
            )
        )
        assert item is not None
        if action != "unchanged":
            ModuleMessageRepository(self.session).enqueue_once(
                ContractEnvelope.build(
                    AcquisitionResultV1(
                        snapshot_id=snapshot.id,
                        source_id=self.source.id,
                        final_url=AnyHttpUrl(snapshot.final_url),
                        fetched_at=snapshot.fetched_at,
                        content_sha256=snapshot.body_sha256,
                    ),
                    contract_type="AcquisitionResult",
                    producer="acquisition",
                    producer_version="0.4.0",
                ),
                consumer="extraction",
            )
        try:
            eligible(self.session, item)
        except EditorialError as exc:
            self.last_result.update(rejection="source_ineligible", source_error=str(exc))
            return None
        content = extract_content(
            item_id=item.id,
            item_version=item.version,
            snapshot_id=snapshot.id,
            url=item.canonical_url,
            title=title,
            body=decode_text(response),
            published_at=None,
            language=item.language,
            is_html=True,
            selectors=self.config.selectors,
            allowed_hosts=self.config.allowed_hosts,
            timezone_hint=self.config.timezone_hint,
        )
        if content.quality_score < 0.6:
            self.last_result.update(rejection="content_quality_insufficient")
            return None
        if INJECTION.search(content.body):
            self.last_result.update(rejection="content_injection_detected")
            return None
        return PairDocument(
            item_id=item.id,
            item_version=item.version,
            snapshot_id=snapshot.id,
            source_id=self.source.id,
            url=str(content.canonical_url),
            title=content.title,
            body=content.body,
            body_hash=content.body_sha256,
            category_proof=proof or "",
        )

    def initial(self, progress: dict[str, Any], count: int) -> tuple[PairDocument, ...]:
        self.check_policy(progress)
        if "initial_links" not in progress:
            response = self.fetch(self.config.list_url, listing=True)
            snapshot = store_snapshot(self.session, self.source.id, response)
            progress["initial_links"] = list(
                release_links(response, self.config.selectors.list_links)
            )
            progress["initial_list_snapshot"] = str(snapshot.id)
            self.save(progress)
        documents = [PairDocument.model_validate(d) for d in progress.get("initial_documents", [])]
        seen = {d.body_hash for d in documents}
        index = progress.get("initial_index", 0)
        links = progress["initial_links"]
        while len(documents) < count:
            if index >= len(links):
                category_search = progress.setdefault(
                    "initial_category_search",
                    {"query": self.category, "next_page": 1, "complete": False},
                )
                if category_search["complete"]:
                    break
                page = category_search["next_page"]
                url = keyword_search_url(self.category, page)
                response = self.fetch(url, search=True)
                snapshot = store_snapshot(self.session, self.source.id, response)
                entries, last_page = keyword_search_results(response, page)
                additions = [entry for entry in entries if entry["url"] not in links]
                for entry in additions:
                    links.append(entry["url"])
                    progress.setdefault("initial_search_metadata", {})[entry["url"]] = {
                        **entry,
                        "snapshot_id": str(snapshot.id),
                        "search_url": url,
                    }
                progress["initial_searches"] = [
                    *progress.get("initial_searches", []),
                    {
                        "query": self.category,
                        "page": page,
                        "url": url,
                        "snapshot_id": str(snapshot.id),
                        "status_code": response.status_code,
                        "links": [entry["url"] for entry in entries],
                        "saved_article_ids": [entry["article_id"] for entry in additions],
                    },
                ]
                category_search["next_page"] = page + 1
                category_search["complete"] = page >= last_page or not entries
                self.save(progress)
                if not additions and not category_search["complete"]:
                    raise CollectionError("PAIR_INITIAL_SEARCH_REPEATED_PAGE")
                continue
            metadata = progress.get("initial_search_metadata", {}).get(links[index], {})
            excluded = excluded_title_terms(metadata.get("title", ""))
            if excluded:
                doc = None
                self.last_result = {
                    "title": metadata["title"],
                    "title_exclusion_terms": list(excluded),
                    "rejection": "title_excluded",
                    "title_source": "initial_category_search",
                    "search_snapshot_id": metadata["snapshot_id"],
                }
            else:
                doc = self.document(links[index], metadata.get("search_url", self.config.list_url))
                if doc is not None and metadata:
                    category_text = norm(embedding_text(doc)[0]).replace("\ufffd", "")
                    self.last_result["initial_category_text_match"] = (
                        norm(self.category) in category_text
                    )
                    if not self.last_result["initial_category_text_match"]:
                        self.last_result["rejection"] = "initial_category_keyword_missing"
                        doc = None
            rejection = (
                self.last_result.get("rejection", "source_ineligible")
                if doc is None
                else "duplicate_body"
                if doc.body_hash in seen
                else None
            )
            progress["initial_results"] = [
                *progress.get("initial_results", []),
                {
                    "url": links[index],
                    "rank": index + 1,
                    "item_id": str(doc.item_id) if doc else None,
                    "rejection": rejection,
                    "acquisition": dict(self.last_result),
                },
            ]
            index += 1
            if doc is not None and doc.body_hash not in seen:
                documents.append(doc)
                seen.add(doc.body_hash)
            progress["initial_documents"] = [d.model_dump(mode="json") for d in documents]
            progress["initial_index"] = index
            self.save(progress)
        return tuple(documents)

    def search(
        self, progress: dict[str, Any], keywords: CategoryKeywords, count: int
    ) -> tuple[PairDocument, ...]:
        self.check_policy(progress)
        identity = canonical_payload_hash(
            {
                "keywords": keywords.model_dump(mode="json"),
                "category": self.category,
                "policy": SEARCH_POLICY,
                "acquisition_policy": ACQUISITION_POLICY,
                "title_exclusion_terms": TITLE_EXCLUSION_TERMS,
                "results_per_keyword": self.results_per_keyword,
            }
        )
        if progress.get("search_identity", identity) != identity or (
            "searches" in progress and progress.get("search_policy") != SEARCH_POLICY
        ):
            raise CollectionError("PAIR_SEARCH_CHECKPOINT_INCOMPATIBLE")
        progress.update(
            search_identity=identity,
            search_policy=SEARCH_POLICY,
            results_per_keyword=self.results_per_keyword,
            pagination="public_keyword_search_40_per_page",
        )
        keyword_results = progress.setdefault("keyword_results", {})
        article_counts = progress.setdefault("article_keyword_counts", {})
        keyword_index = progress.get("keyword_index", 0)
        # Search each label on its own: adding the category to a loose search can
        # make category-only hits look like matches for every distinctive keyword.
        while keyword_index < len(keywords.terms):
            term = keywords.terms[keyword_index]
            current = keyword_results.setdefault(
                term.key,
                {
                    "keyword_key": term.key,
                    "label": term.label,
                    "query": term.label,
                    "results": [],
                    "next_page": 1,
                    "complete": False,
                    "end_reason": None,
                },
            )
            while not current["complete"]:
                page = current["next_page"]
                url = keyword_search_url(term.label, page)
                response = self.fetch(url, search=True)
                snapshot = store_snapshot(self.session, self.source.id, response)
                try:
                    entries, last_page = keyword_search_results(response, page)
                except CollectionError:
                    progress["search_failures"] = [
                        *progress.get("search_failures", []),
                        {
                            "keyword_key": term.key,
                            "query": term.label,
                            "page": page,
                            "url": url,
                            "snapshot_id": str(snapshot.id),
                            "status_code": response.status_code,
                        },
                    ]
                    self.save(progress)
                    raise
                seen = {row["article_id"] for row in current["results"]}
                additions = []
                for rank, entry in enumerate(entries, 1):
                    if entry["article_id"] in seen or len(seen) >= self.results_per_keyword:
                        continue
                    result = {**entry, "page": page, "rank": rank, "snapshot_id": str(snapshot.id)}
                    current["results"].append(result)
                    seen.add(entry["article_id"])
                    additions.append(entry["article_id"])
                    counter = article_counts.setdefault(
                        entry["article_id"],
                        {
                            **entry,
                            "keyword_keys": [],
                            "keyword_count": 0,
                        },
                    )
                    if term.key not in counter["keyword_keys"]:
                        counter["keyword_keys"].append(term.key)
                    counter["keyword_count"] = len(counter["keyword_keys"])
                    counter["title_exclusion_terms"] = list(
                        dict.fromkeys(
                            [
                                *counter.get("title_exclusion_terms", []),
                                *excluded_title_terms(entry["title"]),
                            ]
                        )
                    )
                progress["searches"] = [
                    *progress.get("searches", []),
                    {
                        "keyword_key": term.key,
                        "query": term.label,
                        "page": page,
                        "url": url,
                        "snapshot_id": str(snapshot.id),
                        "at": response.fetched_at.isoformat(),
                        "status_code": response.status_code,
                        "links": [entry["url"] for entry in entries],
                        "saved_article_ids": additions,
                        "last_page": last_page,
                        "scope": "keyword_search_without_category_tag_requirement",
                    },
                ]
                if len(seen) >= self.results_per_keyword:
                    current.update(complete=True, end_reason="result_limit")
                elif page >= last_page or not entries:
                    current.update(complete=True, end_reason="results_exhausted")
                elif not additions:
                    # A repeated response is not evidence that the result set ended.
                    self.save(progress)
                    raise CollectionError("PAIR_SEARCH_REPEATED_PAGE")
                else:
                    current["next_page"] = page + 1
                self.save(progress)
            keyword_index += 1
            progress["keyword_index"] = keyword_index
            self.save(progress)
        progress["keyword_search_complete"] = True
        if "candidate_urls" not in progress:
            for row in article_counts.values():
                row["title_exclusion_terms"] = list(
                    dict.fromkeys(
                        [
                            *row.get("title_exclusion_terms", []),
                            *excluded_title_terms(row["title"]),
                        ]
                    )
                )
                row["candidate_eligible"] = (
                    row["keyword_count"] >= 3 and not row["title_exclusion_terms"]
                )
            candidates = sorted(
                (row for row in article_counts.values() if row["candidate_eligible"]),
                key=lambda row: (-row["keyword_count"], row["article_id"]),
            )
            progress["candidate_urls"] = [row["url"] for row in candidates]
            progress["search_unique_articles"] = len(article_counts)
            progress["search_three_keyword_hits_before_title_filter"] = sum(
                row["keyword_count"] >= 3 for row in article_counts.values()
            )
            progress["candidate_exclusions"] = [
                {
                    "url": row["url"],
                    "title": row["title"],
                    "search_keyword_count": row["keyword_count"],
                    "rejection": "title_excluded",
                    "title_exclusion_terms": row["title_exclusion_terms"],
                }
                for row in article_counts.values()
                if row["keyword_count"] >= 3 and row["title_exclusion_terms"]
            ]
            progress["search_candidates_three_keywords"] = len(candidates)
            progress["candidate_index"] = 0
            self.save(progress)
        documents = [PairDocument.model_validate(d) for d in progress.get("accepted", [])]
        body_hashes = {d.body_hash for d in documents}
        urls = progress["candidate_urls"]
        index = progress.get("candidate_index", 0)
        while len(documents) < count and index < len(urls):
            url = urls[index]
            doc = self.document(url, None)
            hits = keyword_match(doc, keywords) if doc is not None else ()
            rejection = (
                self.last_result.get("rejection", "source_ineligible")
                if doc is None
                else "fewer_than_three_keywords"
                if len(hits) < 3
                else "duplicate_body"
                if doc.body_hash in body_hashes
                else None
            )
            counter = article_counts[url]
            progress["results"] = [
                *progress.get("results", []),
                {
                    "url": url,
                    "rank": index + 1,
                    "item_id": str(doc.item_id) if doc else None,
                    "search_keyword_keys": list(counter["keyword_keys"]),
                    "search_keyword_count": counter["keyword_count"],
                    "hits": list(hits),
                    "rejection": rejection,
                    "acquisition": dict(self.last_result),
                },
            ]
            if doc is not None and rejection is None:
                documents.append(doc)
                body_hashes.add(doc.body_hash)
            index += 1
            progress.update(
                candidate_index=index, accepted=[d.model_dump(mode="json") for d in documents]
            )
            self.save(progress)
        progress["search_complete"] = True
        progress["search_end_reason"] = (
            "document_limit" if len(documents) >= count else "aggregated_candidates_finished"
        )
        self.save(progress)
        return tuple(documents)
