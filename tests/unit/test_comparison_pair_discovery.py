from dataclasses import replace
from datetime import UTC, datetime
from math import nan
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.ai.provider import AIResponse
from app.ai.runner import AIRunner
from app.contracts.comparison_pair_discovery_v3 import (
    CategoryKeywords,
    ComparisonAxis,
    DocumentFeatures,
    FeatureCell,
    PairDiscoveryRequest,
    PairDocument,
    PairProduct,
    SearchTerm,
    SourceQuote,
)
from app.core.comparison_pair_discovery import (
    aggregate_vectors,
    bind_quote_offsets,
    coverage,
    distinct_grounded_keywords,
    distinctive_keywords,
    embedding_text,
    excluded_title_terms,
    matching_terms,
    ranked_pairs,
    text_hash,
    third_ranking,
    validate_distinction,
    validate_features,
    validate_terms,
)
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.comparison_embeddings import (
    EmbeddingResponse,
    OpenAIEmbeddings,
    embedding_chunks,
)
from app.infrastructure.comparison_retrieval import Embedding
from app.infrastructure.db.models import ArticleDraft, Item, Publication, Source
from app.infrastructure.prtimes_pair_acquisition import native_search_url, release_links
from app.modules.acquisition.http import FetchResponse
from app.orchestration.comparison_pair_discovery import PairDiscoveryService, export_pair_run

LABELS = ("automation", "cloud", "sensor")


def document(index, source_id=None, item_id=None, extra=""):
    body = f"Acme{index} Widget{index} automation cloud sensor. " + extra
    return PairDocument(
        item_id=item_id or UUID(int=index + 1),
        item_version=1,
        snapshot_id=uuid4(),
        source_id=source_id or UUID(int=100),
        url=f"https://prtimes.jp/main/html/rd/p/{index}.1.html",
        title=f"Widget{index}",
        body=body,
        body_hash=text_hash(body),
        category_proof="/topics/keywords/IoT",
    )


def quote(doc):
    return SourceQuote(item_id=doc.item_id, start=0, end=len(doc.body), quote=doc.body)


def keywords(doc):
    return CategoryKeywords(
        terms=tuple(
            SearchTerm(
                key=label,
                label=label,
                evidence=(quote(doc),),
                distinction_reason="Separates a documented capability within the category",
            )
            for label in LABELS
        ),
        reason="Distinct characteristics",
    )


def axes(doc):
    return tuple(
        ComparisonAxis(**term.model_dump(), question="How does " + term.label + " work?")
        for term in keywords(doc).terms
    )


def product(doc):
    index = doc.title.removeprefix("Widget")
    return PairProduct(
        item_id=doc.item_id, name=doc.title, organization="Acme" + index, evidence=(quote(doc),)
    )


def features(doc, missing=()):
    return DocumentFeatures(
        product=product(doc),
        cells=tuple(
            FeatureCell(
                item_id=doc.item_id,
                axis_key=label,
                status="unknown" if label in missing else "supported",
                answer="" if label in missing else label,
                conditions="",
                evidence=() if label in missing else (quote(doc),),
            )
            for label in LABELS
        ),
    )


class Acquisition:
    def __init__(self, docs):
        self.docs, self.callback = docs, lambda progress: None
        self.initial_calls, self.search_calls = 0, 0

    def initial(self, progress, count):
        self.initial_calls += 1
        return tuple(self.docs[:count])

    def search(self, progress, terms, count):
        self.search_calls += 1
        progress["accepted"] = [d.model_dump(mode="json") for d in self.docs[:count]]
        progress["search_complete"] = True
        self.callback(progress)
        return tuple(self.docs[:count])

    def close(self):
        pass


class Vectors:
    def __init__(self):
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        index = int(text.splitlines()[0].removeprefix("Widget"))
        return EmbeddingResponse((1.0, index / 100, 0.0), "embedding-test", 20, "fixture", 1)


class Provider:
    def __init__(
        self,
        docs,
        *,
        comparable=True,
        fail_first_review=False,
        fail_all_reviews=False,
        transient=False,
        missing=None,
    ):
        self.docs = {str(d.item_id): d for d in docs}
        self.calls = []
        self.plan_calls = []
        self.review_calls = []
        self.comparable = comparable
        self.fail_first_review = fail_first_review
        self.fail_all_reviews = fail_all_reviews
        self.transient = 2 if transient else 0
        self.missing = missing or {}

    def generate(self, **kwargs):
        data = kwargs["data"]
        schema = kwargs["schema"]["properties"]
        self.calls.append(kwargs["instructions"])
        if "terms" in schema:
            if "source" in data:
                output = keywords(self.docs[data["source"]["item_id"]]).model_dump(mode="json")
            else:
                output = {"terms": data["grounded_keywords"][0]["terms"], "reason": "Grounded"}
        elif "axes" in schema:
            pair = [self.docs[s["item_id"]] for s in data["sources"]]
            self.plan_calls.append(tuple(d.item_id for d in pair))
            output = {
                "comparable": self.comparable,
                "purpose": "Select a sensor system",
                "reason": "Same task",
                "products": [product(d).model_dump(mode="json") for d in pair],
                "axes": [axis.model_dump(mode="json") for axis in axes(pair[0])],
            }
        elif "product" in schema:
            if self.transient:
                self.transient -= 1
                raise EditorialError("AI_TEMPORARY_QUOTA")
            doc = self.docs[data["source"]["item_id"]]
            output = features(doc, self.missing.get(doc.item_id, ())).model_dump(mode="json")
        else:
            self.review_calls.append(data)
            fail = self.fail_all_reviews or (self.fail_first_review and len(self.review_calls) == 1)
            output = {
                "same_selection_task": not fail,
                "evidence_valid": True,
                "conditions_preserved": True,
                "reason": "Fixture independent review",
                "valid_axis_keys": list(LABELS),
            }
        return AIResponse(output, "fixture", 100, 20, 1)


def prepared(session, count=6, **options):
    source = session.scalar(select(Source).where(Source.key == "vendor-rss"))
    if source is None:
        source = session.scalar(select(Source))
    docs = []
    for i in range(count):
        d = document(i, source.id)
        item = Item(
            id=d.item_id,
            source_id=source.id,
            external_id="pair-fixture-" + str(i),
            canonical_url=d.url,
            title_original=d.title,
            language="en",
            content_text=d.body,
            content_sha256=d.body_hash,
        )
        session.add(item)
        docs.append(d)
    session.commit()
    settings = Settings(
        ai_comparison_planner_model="planner-test",
        ai_comparison_assessor_model="assessor-test",
        ai_comparison_verifier_model="independent-test",
        ai_embedding_model="embedding-test",
        ai_embedding_revision="revision-test",
    )
    acquisition, vector = Acquisition(docs), Vectors()
    provider = Provider(docs, **options)
    service = PairDiscoveryService(
        session, settings, AIRunner(session, settings, provider), acquisition, vector
    )
    acquisition.callback = service.acquisition_checkpoint
    return service, docs, provider, acquisition, vector


def test_exactly_ten_failed_pairs_never_considers_eleventh(acquisition_session):
    service, _, provider, _, _ = prepared(acquisition_session, comparable=False)
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "exhausted", state.reason
    assert state.completed_pairs == len(provider.plan_calls) == 10
    assert len(state.distances) == 15
    assert provider.plan_calls == [(p.left, p.right) for p in state.distances[:10]]
    assert acquisition_session.scalar(select(ArticleDraft)) is None
    assert acquisition_session.scalar(select(Publication)) is None


def test_less_than_ten_pairs_is_candidate_shortage_not_exhaustion(acquisition_session):
    service, _, provider, _, _ = prepared(acquisition_session, count=4, comparable=False)
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "insufficient_pairs"
    assert state.completed_pairs == len(provider.plan_calls) == 6


def test_next_third_candidate_same_pair_and_frozen_axes(acquisition_session, tmp_path):
    service, _, provider, _, _ = prepared(acquisition_session, fail_first_review=True)
    request = PairDiscoveryRequest(source_key="fixture", initial_count=3)
    state = service.run(request)
    assert state.status == "selection_passed", state.reason
    assert state.completed_pairs == 1
    assert len(provider.plan_calls) == 1
    assert len(provider.review_calls) == 2
    assert provider.review_calls[0]["axes"] == provider.review_calls[1]["axes"]
    trials = state.pair_results[0]["trials"]
    assert [trial["passed"] for trial in trials] == [False, True]
    assert trials[0]["distances"]["distance"] <= trials[1]["distances"]["distance"]
    export_pair_run(acquisition_session, request.run_id, tmp_path)
    assert all(
        (tmp_path / name).exists()
        for name in (
            "audit.json",
            "ai-runs.json",
            "pair-distances.csv",
            "third-distances.csv",
            "coverage.csv",
            "report.md",
            "selection.json",
            "comparison.md",
        )
    )


def test_all_thirds_fail_before_next_pair(acquisition_session):
    service, docs, provider, _, _ = prepared(acquisition_session, count=5, fail_all_reviews=True)
    state = service.run(
        PairDiscoveryRequest(source_key="fixture", initial_count=3), call_budget=300
    )
    assert state.status == "exhausted", state.reason
    assert state.completed_pairs == len(provider.plan_calls) == 10
    assert len(state.pair_results) == 10
    assert all(len(pair["trials"]) == len(docs) - 2 for pair in state.pair_results)


def test_budget_pause_resumes_without_reembedding_or_repeating_stages(acquisition_session):
    service, _, provider, acquisition, vectors = prepared(acquisition_session)
    request = PairDiscoveryRequest(source_key="fixture", initial_count=3)
    state = service.run(request, call_budget=11)
    assert state.status == "paused_budget", state.reason
    assert state.completed_pairs == 0
    calls, embedding_calls = len(provider.calls), len(vectors.calls)
    resumed = service.run(request, call_budget=100)
    assert resumed.status == "selection_passed", resumed.reason
    assert len(vectors.calls) == embedding_calls == 6
    assert acquisition.initial_calls == acquisition.search_calls == 1
    assert len(provider.calls) > calls
    repeated = service.run(request)
    assert repeated == resumed


def test_temporary_error_is_not_a_failed_third_or_pair(acquisition_session):
    service, _, provider, _, vectors = prepared(acquisition_session, transient=True)
    request = PairDiscoveryRequest(source_key="fixture", initial_count=3)
    first = service.run(request)
    assert first.status == "waiting_retry", first.reason
    assert first.completed_pairs == 0
    resumed = service.run(request)
    assert resumed.status == "selection_passed", resumed.reason
    assert len(provider.plan_calls) == 1 and len(vectors.calls) == 6


def test_two_of_three_per_axis_with_different_supporting_pairs(acquisition_session):
    service, docs, provider, _, _ = prepared(acquisition_session, count=3)
    provider.missing = {doc.item_id: (LABELS[i],) for i, doc in enumerate(docs)}
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "selection_passed", state.reason
    assert set(state.selected["trial"]["coverage"].values()) == {2}


def test_resume_refuses_changed_model_policy(acquisition_session):
    service, _, _, _, _ = prepared(acquisition_session)
    request = PairDiscoveryRequest(source_key="fixture", initial_count=3)
    assert service.run(request, call_budget=1).status == "paused_budget"
    service.settings = service.settings.model_copy(update={"ai_embedding_model": "another"})
    with pytest.raises(EditorialError, match="PAIR_RESUME_CONFIGURATION_CHANGED"):
        service.run(request)


def test_terms_count_concepts_not_repeats_aliases_or_bigrams():
    doc = document(0)
    terms = keywords(doc).terms
    assert matching_terms("automation automation automation", terms) == ("automation",)
    assert matching_terms("automation cloud sensor", terms) == LABELS
    assert matching_terms("automations cloudy sensors", terms) == ()
    overlap = terms[1].model_copy(update={"aliases": ("automation",)})
    with pytest.raises(EditorialError, match="PAIR_OVERLAPPING_TERMS"):
        validate_terms((terms[0], overlap), {doc.item_id: doc})


def test_url_and_contacts_removed_but_units_and_meaningful_url_remain():
    doc = document(
        0,
        extra="\n仕様: 12GB 上位プラン\n詳細 https://example.com/?utm_source=x\n"
        "お問い合わせ Acme 03-1234-5678\n診断対象URL https://target.example/path",
    )
    clean, removed = embedding_text(doc)
    assert "12GB 上位プラン" in clean
    assert "example.com/?utm_source" not in clean and "03-1234-5678" not in clean
    assert "https://target.example/path" in clean
    assert {r["reason"] for r in removed} >= {"contact", "url"}


def test_exact_distance_ties_and_mean_pair_distance():
    ids = [UUID(int=i) for i in (1, 2, 3, 4)]
    vectors = {
        ids[0]: Embedding("p", "m", "v", (1, 0)),
        ids[1]: Embedding("p", "m", "v", (1, 0)),
        ids[2]: Embedding("p", "m", "v", (0, 1)),
        ids[3]: Embedding("p", "m", "v", (-1, 0)),
    }
    pairs = ranked_pairs(vectors)
    assert len(pairs) == 6 and (pairs[0].left, pairs[0].right) == tuple(ids[:2])
    thirds = third_ranking(pairs[0], ids, vectors)
    assert [row["item_id"] for row in thirds] == [str(ids[2]), str(ids[3])]
    assert [row["distance"] for row in thirds] == [1, 2]
    with pytest.raises(ValueError, match="Incompatible"):
        ranked_pairs({ids[0]: vectors[ids[0]], ids[1]: replace(vectors[ids[1]], model="other")})


@pytest.mark.parametrize("values", [(), (0, 0), (nan, 1)])
def test_invalid_embedding_rejected(values):
    if values == (0, 0):
        with pytest.raises(EditorialError, match="ZERO"):
            aggregate_vectors([values], [1])
    else:
        with pytest.raises(EditorialError):
            aggregate_vectors([values], [1])


def test_long_input_chunks_preserve_entire_source_and_byte_bounds():
    text = "診断対象・条件を保持する文章\n" * 1000
    chunks = embedding_chunks(text)
    assert len(chunks) > 1 and "".join(chunks) == text
    assert all(len(chunk.encode()) <= 6000 for chunk in chunks)


def test_embedding_provider_bounds_and_validates_response():
    def handle(request):
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(
            200,
            json={
                "model": "embedding-test",
                "data": [{"index": 0, "embedding": [1, 0]}],
                "usage": {"total_tokens": 2},
            },
        )

    adapter = OpenAIEmbeddings("test-key", "embedding-test", transport=httpx.MockTransport(handle))
    assert adapter.embed("fixture").values == (1, 0)
    with pytest.raises(EditorialError, match="INPUT_LIMIT"):
        adapter.embed("a" * 6001)


def test_foreign_or_fake_quote_does_not_fill_comparison_cell():
    doc = document(0)
    valid = features(doc)
    invalid = valid.cells[0].model_copy(update={"evidence": (quote(document(1)),)})
    with pytest.raises(EditorialError, match="GROUNDING"):
        validate_features(
            valid.model_copy(update={"cells": (invalid, *valid.cells[1:])}), doc, axes(doc)
        )
    bad = valid.cells[0].model_copy(update={"answer": "999999円"})
    with pytest.raises(EditorialError, match="UNSUPPORTED_NUMBER"):
        validate_features(
            valid.model_copy(update={"cells": (bad, *valid.cells[1:])}), doc, axes(doc)
        )


def test_two_axes_or_one_source_each_fails():
    docs = [document(i) for i in range(3)]
    full = [features(doc, LABELS if i else ()) for i, doc in enumerate(docs)]
    assert sum(count >= 2 for count in coverage(full, axes(docs[0])).values()) == 0
    full = [features(doc, ("sensor",)) for doc in docs]
    assert sum(count >= 2 for count in coverage(full, axes(docs[0])).values()) == 2


def test_product_name_cannot_hide_features_or_release_status_in_identity():
    doc = document(0, extra="available now; scan PDFs supported")
    proposal = features(doc)
    decorated = proposal.product.model_copy(
        update={"name": proposal.product.name + " (available now; scan PDFs supported)"}
    )
    with pytest.raises(EditorialError, match="PAIR_PRODUCT_UNGROUNDED"):
        validate_features(proposal.model_copy(update={"product": decorated}), doc, axes(doc))
    validate_features(proposal, doc, axes(doc))


def test_native_search_links_restrict_to_releases_and_preserve_order():
    response = FetchResponse(
        requested_url=native_search_url("IoT automation cloud sensor"),
        final_url=native_search_url("IoT automation cloud sensor"),
        status_code=200,
        headers={"content-type": "text/html"},
        body=(
            b'<a href="/main/html/rd/p/1.2.html">one</a>'
            b'<a href="https://evil.example/main/html/rd/p/3.4.html">other</a>'
            b'<a href="/main/html/rd/p/1.2.html">duplicate</a>'
            b'<a href="/main/html/rd/p/3.4.html">two</a>'
        ),
        fetched_at=datetime.now(UTC),
    )
    assert release_links(response) == (
        "https://prtimes.jp/main/html/rd/p/1.2.html",
        "https://prtimes.jp/main/html/rd/p/3.4.html",
    )
    assert "page=searchkey" in response.requested_url


def test_contract_limits_fixed_ten_pairs_and_maximum_hundred():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PairDiscoveryRequest(source_key="fixture", pair_limit=11)
    with pytest.raises(ValidationError):
        PairDiscoveryRequest(source_key="fixture", maximum_documents=101)


def test_category_can_keep_fifty_distinct_grounded_keywords():
    from pydantic import ValidationError

    labels = tuple(f"capability{i}" for i in range(51))
    doc = document(0, extra=" ".join(labels))
    terms = tuple(
        SearchTerm(
            key=label,
            label=label,
            evidence=(quote(doc),),
            distinction_reason="Distinct documented technical capability",
        )
        for label in labels
    )
    selected = CategoryKeywords(terms=terms[:50], reason="Fifty supported concepts")
    validate_terms(selected.terms, {doc.item_id: doc})
    validate_distinction(selected)
    assert len(distinctive_keywords(selected, "IoT")[0].terms) == 50
    with pytest.raises(ValidationError):
        CategoryKeywords(terms=terms, reason="Over limit")


def test_keyword_roles_have_room_for_fifty_outputs_without_expanding_other_roles(
    acquisition_session,
):
    service, docs, provider, _, _ = prepared(acquisition_session)
    seen = []

    def generate(**kwargs):
        seen.append(kwargs["max_output_tokens"])
        return AIResponse(keywords(docs[0]).model_dump(mode="json"), "fixture")

    provider.generate = generate
    runner = AIRunner(acquisition_session, service.settings, provider)
    result, _ = runner.run(
        "pair_category", docs[0].item_id, {"padding": "x" * 50001}, CategoryKeywords
    )
    assert result is not None and seen == [16000]
    with pytest.raises(EditorialError, match="AI_INPUT_TOO_LARGE"):
        runner.run("pair_plan", docs[0].item_id, {"padding": "x" * 50001}, CategoryKeywords)
    assert seen == [16000]


def prtimes_acquisition(
    session,
    monkeypatch,
    pages_per_run=20,
    empty_search=False,
    search_pages=None,
    search_requests=None,
    results_per_keyword=150,
    release_titles=None,
    search_titles=None,
    release_words=None,
):
    from app.infrastructure.prtimes_pair_acquisition import PRTimesPairAcquisition
    from app.modules.acquisition.http import SafeHttpClient
    from tests.unit.test_web_collection import web_source

    source = web_source(session)
    source.terms_url = "https://prtimes.jp/main/html/kiyaku"
    source.config = {
        **source.config,
        "list_url": "https://prtimes.jp/topics/keywords/IoT",
        "allowed_hosts": ["prtimes.jp"],
        "allow_url_patterns": [r"^https://prtimes\.jp/main/html/rd/p/[0-9]+\.[0-9]+\.html$"],
        "deny_url_patterns": [r"/api/(?!keyword_search\.php/search(?:\?|$))"],
        "max_pages_per_run": pages_per_run,
        "selectors": {
            "list_links": "a.release",
            "title": "h1",
            "published_at": "time[datetime]",
            "body": "article",
        },
    }
    session.commit()
    requests = []
    urls = [f"https://prtimes.jp/main/html/rd/p/{i}.1.html" for i in (1, 2, 3)]

    def handle(request):
        path = request.url.path
        requests.append(path)
        if path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", headers={"Content-Type": "text/plain"}
            )
        if path == "/main/html/kiyaku":
            body = "<main>Approved collection terms</main>"
        elif path == "/api/keyword_search.php/search":
            query = request.url.params.get("keyword", "")
            page = int(request.url.params["page"])
            if search_requests is not None:
                search_requests.append((query, page))
            selected = (
                search_pages.get((query, page), []) if search_pages is not None else [1, 2, 3]
            )
            if empty_search and "cloud" in query:
                selected = []
            last = (
                max((p for q, p in search_pages if q == query), default=page)
                if search_pages is not None
                else page
            )
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "message": "ok",
                    "data": {
                        "current_page": page,
                        "last_page": last,
                        "limit": 40,
                        "total": last * 40 if selected else 0,
                        "release_list": [
                            {
                                "company_id": 1,
                                "release_id": i,
                                "title": (search_titles or {}).get(i, f"Widget{i}"),
                                "release_url": f"/main/html/rd/p/{i}.1.html",
                            }
                            for i in selected
                        ],
                    },
                },
            )
        elif path.startswith("/topics/") or path == "/main/action.php":
            body = (
                "<main>"
                + "".join(f'<a class="release" href="{url}">release</a>' for url in urls)
                + "</main>"
            )
        else:
            index = path.rsplit("/", 1)[-1].split(".")[0]
            tag = "other" if index == "1" else "IoT"
            words = "automation cloud" if index == "2" else "automation cloud sensor"
            words = (release_words or {}).get(int(index), words + " IoT")
            title = (release_titles or {}).get(int(index), f"Widget{index}")
            body = (
                f"<html lang='en'><main><h1>{title}</h1>"
                "<time datetime='2026-10-11T01:00:00Z'></time><article>"
                + (f"Acme{index} Widget{index} {words}. Documented industrial specifications. " * 8)
                + f'</article><dl><dt>キーワード</dt><dd><a href="/topics/keywords/{tag}">'
                f"{tag}</a></dd></dl>"
                + '<aside><a href="/topics/keywords/IoT">IoT</a></aside></main></html>'
            )
        return httpx.Response(200, text=body, headers={"Content-Type": "text/html"})

    def build(config):
        return SafeHttpClient(
            allowed_hosts=config.allowed_hosts,
            user_agent="TestNewsBot",
            resolver=lambda _: ["93.184.216.34"],
            transport=httpx.MockTransport(handle),
            min_delay_seconds=0,
            sleep=lambda _: None,
        )

    monkeypatch.setattr("app.infrastructure.prtimes_pair_acquisition.build_http", build)
    checkpoints = []
    adapter = PRTimesPairAcquisition(
        session,
        source.key,
        lambda p: checkpoints.append(dict(p)),
        lambda: None,
        results_per_keyword=results_per_keyword,
    )
    return adapter, requests, checkpoints


def test_prtimes_native_acquisition_accepts_no_category_tag_but_requires_three_body_terms(
    acquisition_session, monkeypatch
):
    adapter, requests, checkpoints = prtimes_acquisition(acquisition_session, monkeypatch)
    try:
        initial = adapter.initial({}, 3)
        assert len(initial) == 3
        progress = {}
        accepted = adapter.search(progress, keywords(initial[0]), 100)
        assert [doc.title for doc in accepted] == ["Widget1", "Widget3"]
        assert all(doc.category_proof == "" for doc in accepted)
        assert progress["category_tag_required"] is False
        assert progress["search_complete"]
        assert len(progress["searches"]) == 3
        assert set(progress["keyword_results"]) == set(LABELS)
        assert all(r["keyword_count"] == 3 for r in progress["article_keyword_counts"].values())
        assert [r["rejection"] for r in progress["results"]] == [
            None,
            "fewer_than_three_keywords",
            None,
        ]
        assert all(r["acquisition"]["snapshot_id"] for r in progress["results"])
        assert "/api/keyword_search.php/search" in requests
        assert all(
            not path.startswith("/api") or path == "/api/keyword_search.php/search"
            for path in requests
        )
        assert checkpoints
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "title,matched",
    [
        ("AI検索の比較調査を公開", ("調査",)),
        ("新サービスの導入事例レポート", ("事例", "レポート")),
        ("無料ホワイトペーパーを公開", ("ホワイトペーパー",)),
        ("生成AIセミナーを開催", ("セミナー", "開催")),
        ("生成AIが選ぶランキング", ("ランキング",)),
        ("新しい書籍を出版", ("書籍", "出版")),
        ("2026年9月調\ufffd査", ("調査",)),
        ("導入事\x00例を紹介", ("事例",)),
        ("ベストセラー2冠", ("ベストセラー",)),
        ("AI実装現場を取材", ("取材",)),
        ("動画制作の登壇者と交流会", ("登壇", "交流会")),
        ("科学実験イベント」開催", ("開催",)),
        ("社員決起大会", ("大会",)),
        ("留学生のリアルな声を公開", ("声を公開",)),
        ("産業展に出展します", ("出展",)),
        ("ソフトウェアプラットフォーム会社を設立", ("設立",)),
        ("GEO領域への事業重点化を発表", ("事業重点化",)),
        ("AIエージェントの提供開始", ()),
        ("イベント管理サービスの新機能", ()),
    ],
)
def test_title_filter_excludes_release_types_without_excluding_product_launches(title, matched):
    assert excluded_title_terms(title) == matched


def test_initial_skips_non_product_titles_and_preserves_decisions_on_resume(
    acquisition_session,
    monkeypatch,
):
    from app.modules.acquisition.http import CollectionError

    progress = {}
    titles = {1: "AI市場調査の事例を公開"}
    adapter, _, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        2,
        release_titles=titles,
    )
    try:
        with pytest.raises(CollectionError, match="PAGE_LIMIT"):
            adapter.initial(progress, 2)
        assert progress["initial_index"] == 1
        assert progress["initial_documents"] == []
        excluded = progress["initial_results"][0]
        assert excluded["rejection"] == "title_excluded"
        assert excluded["acquisition"]["title_exclusion_terms"] == ["調査", "事例"]
    finally:
        adapter.close()
    adapter, requests, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        2,
        release_titles=titles,
    )
    try:
        assert [d.title for d in adapter.initial(progress, 2)] == ["Widget2", "Widget3"]
        assert len(progress["initial_results"]) == 3
        assert "/main/html/rd/p/1.1.html" not in requests
    finally:
        adapter.close()


def test_search_excludes_metadata_titles_before_fetch_and_rechecks_article_title(
    acquisition_session,
    monkeypatch,
):
    adapter, requests, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        search_titles={1: "生成AI市場調査", 2: "新サービス提供開始"},
        release_titles={2: "新サービスの導入事例"},
    )
    progress = {}
    try:
        accepted = adapter.search(progress, keywords(document(0)), 100)
        assert [doc.title for doc in accepted] == ["Widget3"]
        assert progress["search_three_keyword_hits_before_title_filter"] == 3
        assert progress["search_candidates_three_keywords"] == 2
        assert progress["candidate_exclusions"][0]["title_exclusion_terms"] == ["調査"]
        assert progress["candidate_urls"] == [
            "https://prtimes.jp/main/html/rd/p/2.1.html",
            "https://prtimes.jp/main/html/rd/p/3.1.html",
        ]
        assert "/main/html/rd/p/1.1.html" not in requests
        excluded = progress["results"][0]
        assert excluded["rejection"] == "title_excluded"
        assert excluded["acquisition"]["title_exclusion_terms"] == ["事例"]
        assert excluded["acquisition"]["snapshot_id"]
        # Search IDs and distinct keyword counts survive the title filter.
        assert all(len(row["results"]) == 3 for row in progress["keyword_results"].values())
        assert all(row["keyword_count"] == 3 for row in progress["article_keyword_counts"].values())
    finally:
        adapter.close()


def test_initial_replenishes_filtered_category_list_using_public_category_word_search(
    acquisition_session,
    monkeypatch,
):
    adapter, requests, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        release_titles={1: "生成AI市場調\ufffd査"},
        search_titles={4: "生成AIの調査レポート"},
        search_pages={("IoT", 1): [1, 2, 3, 4, 6, 5]},
        release_words={6: "automation cloud sensor unrelated barbecue"},
    )
    progress = {}
    try:
        initial = adapter.initial(progress, 3)
        assert [doc.title for doc in initial] == ["Widget2", "Widget3", "Widget5"]
        assert "/main/html/rd/p/4.1.html" not in requests
        assert len(progress["initial_searches"]) == 1
        assert progress["initial_searches"][0]["query"] == "IoT"
        assert initial[-1].category_proof == progress["initial_searches"][0]["url"]
        assert [row["rejection"] for row in progress["initial_results"]] == [
            "title_excluded",
            None,
            None,
            "title_excluded",
            "initial_category_keyword_missing",
            None,
        ]
    finally:
        adapter.close()


@pytest.mark.parametrize("stage", ["initial", "search"])
def test_old_acquisition_checkpoint_cannot_mix_title_and_tag_policies(
    acquisition_session,
    monkeypatch,
    stage,
):
    from app.modules.acquisition.http import CollectionError

    adapter, requests, _ = prtimes_acquisition(acquisition_session, monkeypatch)
    progress = {"initial_links": []} if stage == "initial" else {"searches": []}
    try:
        with pytest.raises(CollectionError, match="PAIR_ACQUISITION_CHECKPOINT_INCOMPATIBLE"):
            if stage == "initial":
                adapter.initial(progress, 3)
            else:
                adapter.search(progress, keywords(document(0)), 100)
        assert requests == []
    finally:
        adapter.close()


def test_pair_selection_accepts_empty_category_proof(acquisition_session):
    service, docs, _, acquisition, _ = prepared(acquisition_session)
    acquisition.docs = [doc.model_copy(update={"category_proof": ""}) for doc in docs]
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "selection_passed", state.reason


@pytest.mark.parametrize("index", [0, 3])
def test_pair_selection_rejects_excluded_titles_from_alternate_acquisition_ports(
    acquisition_session,
    index,
):
    service, docs, _, acquisition, vectors = prepared(acquisition_session)
    acquisition.docs[index] = docs[index].model_copy(update={"title": "生成AI市場調査"})
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "waiting_retry"
    assert "TITLE_EXCLUDED" in state.reason or "GROUP_A_INVALID" in state.reason
    assert vectors.calls == []


def test_prtimes_page_limit_keeps_queue_and_resumes_next_batch(acquisition_session, monkeypatch):
    from app.modules.acquisition.http import CollectionError

    adapter, _, _checkpoints = prtimes_acquisition(acquisition_session, monkeypatch, 2)
    progress = {}
    try:
        with pytest.raises(CollectionError, match="PAGE_LIMIT"):
            adapter.initial(progress, 3)
        assert progress["initial_index"] == 1
        assert len(progress["initial_documents"]) == 1
    finally:
        adapter.close()
    adapter, _, _ = prtimes_acquisition(acquisition_session, monkeypatch, 2)
    try:
        # The cached listing does not consume a page in this invocation.
        resumed = adapter.initial(progress, 3)
        assert len(resumed) == 3
        assert progress["initial_index"] == 3
    finally:
        adapter.close()


@pytest.mark.parametrize("missing", ["title", "count", "message", "query", "none"])
def test_native_404_is_empty_only_with_query_echo_zero_count_and_exact_message(missing):
    from app.infrastructure.prtimes_pair_acquisition import search_result_links
    from app.modules.acquisition.http import CollectionError

    query = "生成AI RAG"
    title = ("別の語" if missing == "query" else query) + "に関するプレスリリース・ニュースリリース"
    body = "" if missing == "title" else f"<title>{title}</title>"
    body += "検索結果\uff1a" + ("1" if missing == "count" else "0") + "件"
    body += "" if missing == "message" else "に合致するプレスリリースはありませんでした。"
    response = FetchResponse(
        native_search_url(query),
        native_search_url(query),
        404,
        {"content-type": "text/html"},
        body.encode(),
        datetime.now(UTC),
    )
    if missing == "none":
        assert search_result_links(response, query) == ()
    else:
        with pytest.raises(CollectionError, match="PAIR_SEARCH_NOT_FOUND_UNCONFIRMED"):
            search_result_links(response, query)


def test_public_zero_search_is_recorded_and_does_not_block_following_keywords(
    acquisition_session,
    monkeypatch,
):
    adapter, _, _ = prtimes_acquisition(acquisition_session, monkeypatch, empty_search=True)
    try:
        initial = adapter.initial({}, 3)
        progress = {}
        accepted = adapter.search(progress, keywords(initial[0]), 100)
        assert len(accepted) == 0  # Only two different searches hit each URL.
        assert progress["search_complete"]
        empty = progress["searches"][1]
        assert empty["status_code"] == 200 and empty["links"] == []
        assert progress["keyword_results"]["cloud"]["end_reason"] == "results_exhausted"
        from app.infrastructure.db.models import RawSnapshot

        assert acquisition_session.get(RawSnapshot, UUID(empty["snapshot_id"])).status_code == 200
    finally:
        adapter.close()


def test_single_keyword_saves_150_unique_ids_across_four_public_pages(
    acquisition_session,
    monkeypatch,
):
    pages = {("automation", p): list(range((p - 1) * 40 + 1, p * 40 + 1)) for p in range(1, 5)}
    queries = []
    adapter, requests, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        search_pages=pages,
        search_requests=queries,
    )
    progress = {}
    terms = keywords(document(0)).model_copy(update={"terms": (keywords(document(0)).terms[0],)})
    try:
        assert adapter.search(progress, terms, 100) == ()
        saved = progress["keyword_results"]["automation"]
        assert len(saved["results"]) == len(progress["article_keyword_counts"]) == 150
        assert saved["end_reason"] == "result_limit"
        assert queries == [("automation", p) for p in range(1, 5)]
        assert all(row["keyword_count"] == 1 for row in progress["article_keyword_counts"].values())
        assert not any(path.startswith("/main/html/rd/p/") for path in requests)
    finally:
        adapter.close()


def test_keyword_count_deduplicates_links_and_pages_and_filters_before_body_fetch(
    acquisition_session,
    monkeypatch,
):
    pages = {
        ("automation", 1): [1, 1, 2],
        ("automation", 2): [1, 3],
        ("cloud", 1): [2, 3],
        ("sensor", 1): [3],
    }
    queries = []
    adapter, requests, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        search_pages=pages,
        search_requests=queries,
    )
    progress = {}
    try:
        accepted = adapter.search(progress, keywords(document(0)), 100)
        assert [d.title for d in accepted] == ["Widget3"]
        counts = progress["article_keyword_counts"]
        assert [
            counts[f"https://prtimes.jp/main/html/rd/p/{i}.1.html"]["keyword_count"]
            for i in (1, 2, 3)
        ] == [1, 2, 3]
        assert len(progress["keyword_results"]["automation"]["results"]) == 3
        assert queries == [("automation", 1), ("automation", 2), ("cloud", 1), ("sensor", 1)]
        assert [path for path in requests if path.startswith("/main/html/rd/p/")] == [
            "/main/html/rd/p/3.1.html"
        ]
        assert progress["results"][0]["search_keyword_count"] == 3
    finally:
        adapter.close()


def test_keyword_search_resume_does_not_refetch_pages_or_inflate_counts(
    acquisition_session,
    monkeypatch,
):
    from app.modules.acquisition.http import CollectionError

    pages = {("automation", p): list(range((p - 1) * 40 + 1, p * 40 + 1)) for p in range(1, 5)}
    queries = []
    terms = keywords(document(0)).model_copy(update={"terms": (keywords(document(0)).terms[0],)})
    progress = {}
    adapter, _, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        pages_per_run=2,
        search_pages=pages,
        search_requests=queries,
    )
    try:
        with pytest.raises(CollectionError, match="PAGE_LIMIT"):
            adapter.search(progress, terms, 100)
        assert len(progress["keyword_results"]["automation"]["results"]) == 80
        assert progress["keyword_results"]["automation"]["next_page"] == 3
    finally:
        adapter.close()
    adapter, _, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        pages_per_run=2,
        search_pages=pages,
        search_requests=queries,
    )
    try:
        assert adapter.search(progress, terms, 100) == ()
        assert queries == [("automation", p) for p in range(1, 5)]
        assert len(progress["article_keyword_counts"]) == 150
        assert all(r["keyword_count"] == 1 for r in progress["article_keyword_counts"].values())
        changed = terms.model_copy(update={"terms": keywords(document(0)).terms})
        with pytest.raises(CollectionError, match="PAIR_SEARCH_CHECKPOINT_INCOMPATIBLE"):
            adapter.search(progress, changed, 100)
    finally:
        adapter.close()


def test_repeated_public_page_is_not_false_search_completion(acquisition_session, monkeypatch):
    from app.modules.acquisition.http import CollectionError

    pages = {("automation", 1): [1, 2, 3], ("automation", 2): [1, 2, 3]}
    adapter, _, _ = prtimes_acquisition(acquisition_session, monkeypatch, search_pages=pages)
    terms = keywords(document(0)).model_copy(update={"terms": (keywords(document(0)).terms[0],)})
    progress = {}
    try:
        # A repeated last page is an observed end; add a later page to exercise the incomplete case.
        pages[("automation", 3)] = [4]
        with pytest.raises(CollectionError, match="PAIR_SEARCH_REPEATED_PAGE"):
            adapter.search(progress, terms, 100)
        assert not progress.get("search_complete")
        assert len(progress["article_keyword_counts"]) == 3
        assert all(r["keyword_count"] == 1 for r in progress["article_keyword_counts"].values())
    finally:
        adapter.close()


@pytest.mark.parametrize("fault", ["http", "status", "page", "identity", "host", "total", "json"])
def test_public_search_response_does_not_accept_errors_or_foreign_ids(fault):
    import json

    from app.infrastructure.prtimes_pair_acquisition import (
        keyword_search_results,
        keyword_search_url,
    )
    from app.modules.acquisition.http import CollectionError

    payload = {
        "status": 200,
        "data": {
            "current_page": 1,
            "last_page": 1,
            "total": 1,
            "limit": 40,
            "release_list": [
                {
                    "company_id": 1,
                    "release_id": 1,
                    "title": "Widget1",
                    "release_url": "/main/html/rd/p/1.1.html",
                }
            ],
        },
    }
    if fault == "status":
        payload["status"] = 500
    elif fault == "page":
        payload["data"]["current_page"] = 2
    elif fault == "identity":
        payload["data"]["release_list"][0]["company_id"] = 2
    elif fault == "host":
        payload["data"]["release_list"][0]["release_url"] = (
            "https://other.example/main/html/rd/p/1.1.html"
        )
    elif fault == "total":
        payload["data"]["total"] = 0
    response = FetchResponse(
        keyword_search_url("automation", 1),
        keyword_search_url("automation", 1),
        404 if fault == "http" else 200,
        {"content-type": "application/json"},
        b"invalid" if fault == "json" else json.dumps(payload).encode(),
        datetime.now(UTC),
    )
    with pytest.raises(CollectionError, match="PAIR_SEARCH_RESPONSE_INVALID"):
        keyword_search_results(response, 1)


@pytest.mark.parametrize(
    "path",
    [
        "/api/private?keyword=automation&page=1&limit=40",
        "/api/keyword_search.php/search/internal?keyword=automation&page=1&limit=40",
        "/api/keyword_search.php/search?keyword=automation&page=1&limit=150",
        "/api/keyword_search.php/search?keyword=automation&page=1&limit=40&token=unexpected",
        "/api/keyword_search.php/search?keyword=automation&page=1&page=2&limit=40",
    ],
)
def test_only_exact_public_search_route_and_parameters_are_allowed(
    acquisition_session,
    monkeypatch,
    path,
):
    from app.modules.acquisition.http import CollectionError

    adapter, requests, _ = prtimes_acquisition(acquisition_session, monkeypatch)
    try:
        with pytest.raises(CollectionError, match=r"^(?:PAIR_SEARCH_URL_BLOCKED|URL_BLOCKED)$"):
            adapter.fetch("https://prtimes.jp" + path, search=True)
        assert requests == ["/robots.txt", "/main/html/kiyaku"]
    finally:
        adapter.close()


@pytest.mark.parametrize("exclude_search_title", [False, True])
def test_keyword_results_and_article_counts_are_exported(
    acquisition_session,
    monkeypatch,
    tmp_path,
    exclude_search_title,
):
    import csv

    adapter, _, _ = prtimes_acquisition(
        acquisition_session,
        monkeypatch,
        search_titles={1: "生成AIの調査事例"} if exclude_search_title else None,
    )
    initial = adapter.initial({}, 3)
    settings = Settings(
        ai_comparison_planner_model="planner-test",
        ai_comparison_assessor_model="assessor-test",
        ai_comparison_verifier_model="independent-test",
        ai_embedding_model="embedding-test",
    )
    service = PairDiscoveryService(
        acquisition_session,
        settings,
        AIRunner(acquisition_session, settings, Provider(initial)),
        adapter,
        Vectors(),
    )
    adapter.save = service.acquisition_checkpoint
    state = service.run(PairDiscoveryRequest(source_key=adapter.source.key, initial_count=3))
    assert state.status == "insufficient_sources"
    export_pair_run(acquisition_session, state.request.run_id, tmp_path)
    with (tmp_path / "keyword-search-results.csv").open(encoding="utf-8-sig") as f:
        results = list(csv.DictReader(f))
    with (tmp_path / "article-keyword-counts.csv").open(encoding="utf-8-sig") as f:
        articles = list(csv.DictReader(f))
    assert len(results) == 9 and len(articles) == 3
    assert all(row["keyword_count"] == "3" for row in articles)
    assert sorted(row["body_keyword_count"] for row in articles) == (
        ["", "2", "3"] if exclude_search_title else ["2", "3", "3"]
    )
    if exclude_search_title:
        excluded = next(row for row in articles if row["title"] == "生成AIの調査事例")
        assert excluded["rejection"] == "title_excluded"
        assert excluded["title_exclusion_terms"] == "調査;事例"
        assert excluded["candidate_eligible"] == "False"
    with (tmp_path / "initial-selection.csv").open(encoding="utf-8-sig") as f:
        initial_rows = list(csv.DictReader(f))
    assert len(initial_rows) == 3
    assert [row["title"] for row in initial_rows] == ["Widget1", "Widget2", "Widget3"]


def test_cli_registers_discover_resume_and_export():
    from typer.testing import CliRunner

    from app.cli import app

    result = CliRunner().invoke(app, ["comparison-pair", "--help"])
    assert result.exit_code == 0
    assert all(name in result.output for name in ("discover", "resume", "export"))


def test_exact_quote_offsets_bound_without_changing_or_guessing_evidence():
    doc = document(1)
    incorrect = SourceQuote(item_id=doc.item_id, start=1, end=2, quote="automation")
    terms = CategoryKeywords(
        terms=(SearchTerm(key="automation", label="automation", evidence=(incorrect,)),),
        reason="Grounded",
    )
    result = bind_quote_offsets(terms, {doc.item_id: doc})
    ref = result.terms[0].evidence[0]
    assert doc.body[ref.start : ref.end] == ref.quote == "automation"
    missing = incorrect.model_copy(update={"quote": "invented"})
    with pytest.raises(EditorialError, match="PAIR_GROUNDING_INVALID"):
        bind_quote_offsets(
            terms.model_copy(
                update={"terms": (terms.terms[0].model_copy(update={"evidence": (missing,)}),)}
            ),
            {doc.item_id: doc},
        )
    repeated = doc.model_copy(update={"body": doc.body + "automation"})
    with pytest.raises(EditorialError, match="PAIR_GROUNDING_AMBIGUOUS"):
        bind_quote_offsets(terms, {doc.item_id: repeated})


def test_keywords_merge_shared_forms_and_drop_unquoted_search_terms():
    doc = document(1)
    raw = CategoryKeywords(
        terms=(
            SearchTerm(
                key="automation", label="automation", aliases=("automatic",), evidence=(quote(doc),)
            ),
            SearchTerm(
                key="automatic", label="automatic", aliases=("automation",), evidence=(quote(doc),)
            ),
            SearchTerm(key="invented", label="invented", evidence=(quote(doc),)),
        ),
        reason="Raw proposal",
    )
    result = distinct_grounded_keywords(raw)
    assert len(result.terms) == 1
    assert result.terms[0].key == "automation"
    assert result.terms[0].aliases == ("automatic",)
    validate_terms(result.terms, {doc.item_id: doc})


def test_category_distinction_removes_category_generic_labels_and_broad_aliases():
    doc = document(
        1,
        extra="生成AI AI 要件定義 判断 社内資料 質問 スライド LP 配置 "
        "AIエージェント エージェント OCR スキャンPDF スライド生成 LLMO計測ツール 計測ツール",
    )
    labels = ("生成AI", "要件定義", "判断", "社内資料", "質問", "スライド", "LP", "配置")
    proposal = CategoryKeywords(
        terms=(
            *(
                SearchTerm(key=str(i), label=v, evidence=(quote(doc),))
                for i, v in enumerate(labels)
            ),
            SearchTerm(
                key="agent",
                label="AIエージェント",
                aliases=("AI", "エージェント"),
                evidence=(quote(doc),),
                distinction_reason="自律的な業務実行方式を区別する",
            ),
            SearchTerm(
                key="slides",
                label="スライド生成",
                aliases=("スライド",),
                evidence=(quote(doc),),
                distinction_reason="生成する成果物の機能を区別する",
            ),
            SearchTerm(
                key="llmo",
                label="LLMO計測ツール",
                aliases=("計測ツール",),
                evidence=(quote(doc),),
                distinction_reason="LLM回答での露出計測機能を区別する",
            ),
        ),
        reason="proposal",
    )
    selected, decisions = distinctive_keywords(proposal, "生成AI")
    assert [term.label for term in selected.terms] == [
        "AIエージェント",
        "スライド生成",
        "LLMO計測ツール",
    ]
    assert selected.terms[0].aliases == ("エージェント",)
    assert selected.terms[1].aliases == selected.terms[2].aliases == ()
    assert sum(not d["retained"] for d in decisions) == 8
    assert decisions[-1]["removed_aliases"] == ["計測ツール"]
    # Generic words must not manufacture three matches on an unrelated release.
    assert matching_terms("生成AI AI 質問 社内資料 スライド LP 計測ツール", selected.terms) == ()
    validate_distinction(selected)


def test_category_exclusion_uses_normalized_configured_category_and_keeps_specific_compounds():
    doc = document(1, extra="\uff29\uff4f\uff34 IoTセキュリティ")
    value = CategoryKeywords(
        terms=(
            SearchTerm(key="iot", label="\uff29\uff4f\uff34", evidence=(quote(doc),)),
            SearchTerm(key="security", label="IoTセキュリティ", evidence=(quote(doc),)),
        ),
        reason="proposal",
    )
    result, decisions = distinctive_keywords(value, "iot")
    assert [term.label for term in result.terms] == ["IoTセキュリティ"]
    assert decisions[0]["reason"] == "category_or_generic_label"


@pytest.mark.parametrize(
    "label",
    [
        "API",
        "プロンプト",
        "整合性確認",
        "影響確認",
        "修正案の作成",
        "明示",
        "初回無料",
        "日本語",
        "リアルタイム",
    ],
)
def test_bare_workflow_terms_do_not_fill_fifty_keyword_target(label):
    proposed = CategoryKeywords(
        terms=(
            SearchTerm(
                key="generic",
                label=label,
                evidence=(SourceQuote(item_id=uuid4(), start=0, end=len(label), quote=label),),
                distinction_reason="この語が資料に書かれているため。",
            ),
        ),
        reason="50語候補の評価",
    )
    filtered, decisions = distinctive_keywords(proposed, "生成AI")
    assert not filtered.terms
    assert decisions


def test_sponsorship_announcement_is_excluded_from_product_sources():
    assert excluded_title_terms("企業とのスポンサー契約締結について") == ("スポンサー契約",)


def test_distinctive_label_itself_and_all_search_aliases_must_be_quoted():
    doc = document(1, extra="OCR")
    value = CategoryKeywords(
        terms=(
            SearchTerm(
                key="invented", label="未記載の機能", aliases=("OCR",), evidence=(quote(doc),)
            ),
            SearchTerm(key="ocr", label="OCR", aliases=("光学文字認識",), evidence=(quote(doc),)),
        ),
        reason="proposal",
    )
    result, decisions = distinctive_keywords(value, "生成AI")
    assert len(result.terms) == 1
    assert result.terms[0].label == "OCR" and result.terms[0].aliases == ()
    assert decisions[0]["reason"] == "label_not_quoted"


def test_distinctive_terms_require_an_explanation_of_category_distinction():
    with pytest.raises(EditorialError, match="PAIR_KEYWORD_DISTINCTION_REQUIRED"):
        validate_distinction(
            CategoryKeywords(
                terms=(SearchTerm(key="ocr", label="OCR", evidence=(quote(document(1)),)),),
                reason="Frequently mentioned",
            )
        )


def test_explanatory_fragments_are_not_search_keywords_or_aliases():
    doc = document(
        1,
        extra="AIエージェント AIエージェントを組み込む "
        "文字を選択できないスキャンPDF スキャンPDF ページ順に読み取り",
    )
    labels = ("AIエージェントを組み込む", "文字を選択できないスキャンPDF", "ページ順に読み取り")
    value = CategoryKeywords(
        terms=(
            *(
                SearchTerm(key=str(i), label=label, evidence=(quote(doc),))
                for i, label in enumerate(labels)
            ),
            SearchTerm(
                key="agent", label="AIエージェント", aliases=(labels[0],), evidence=(quote(doc),)
            ),
        ),
        reason="proposal",
    )
    result, decisions = distinctive_keywords(value, "生成AI")
    assert [term.label for term in result.terms] == ["AIエージェント"]
    assert result.terms[0].aliases == ()
    assert all(d["reason"] == "explanatory_clause_not_keyword" for d in decisions[:3])


def test_partial_export_keeps_unfinished_pair_ranking_and_ai_attempts(
    acquisition_session, tmp_path
):
    import csv
    import json

    service, _, _, _, _ = prepared(acquisition_session, fail_all_reviews=True)
    request = PairDiscoveryRequest(source_key="fixture", initial_count=3)
    state = service.run(request, call_budget=15)
    assert state.status == "paused_budget", state.reason
    assert state.completed_pairs == 0
    progress = state.stages["pair-progress:1"]
    assert len(progress["trials"]) == 1
    export_pair_run(acquisition_session, request.run_id, tmp_path)
    with (tmp_path / "third-distances.csv").open(encoding="utf-8-sig") as stream:
        assert len(list(csv.DictReader(stream))) == len(progress["ranking"])
    audit = json.loads((tmp_path / "audit.json").read_text())
    assert len(audit["ai_runs"]) == len(state.ai_attempt_ids) == state.ai_calls


def test_hundred_documents_keep_all_4950_distances_but_only_ten_pair_trials(acquisition_session):
    service, _, provider, _, _ = prepared(acquisition_session, count=100, comparable=False)
    state = service.run(
        PairDiscoveryRequest(source_key="fixture", initial_count=10), call_budget=140
    )
    assert state.status == "exhausted", state.reason
    assert len(state.group_a) == 100
    assert len(state.distances) == 4950
    assert state.completed_pairs == len(provider.plan_calls) == 10


def test_exhaustion_cannot_be_loaded_with_fewer_than_ten_recorded_pairs():
    from pydantic import ValidationError

    from app.contracts.comparison_pair_discovery_v3 import PairDiscoveryState

    with pytest.raises(ValidationError, match="ten completed unsuccessful pairs"):
        PairDiscoveryState(
            request=PairDiscoveryRequest(source_key="fixture"),
            fingerprint="test",
            status="exhausted",
        )


def test_invalid_category_proposal_is_not_cached_as_accepted(acquisition_session):
    from app.ai.provider import AIResponse

    service, _, provider, _, _ = prepared(acquisition_session)
    request = PairDiscoveryRequest(source_key="fixture", initial_count=3)
    generate = provider.generate

    def incorrect_category(**kwargs):
        response = generate(**kwargs)
        if "terms" in kwargs["schema"]["properties"] and "source" not in kwargs["data"]:
            data = response.output
            data["terms"] = [dict(data["terms"][0], label="Acme0", aliases=[])]
            return AIResponse(data, "fixture")
        return response

    provider.generate = incorrect_category
    state = service.run(request)
    assert state.status == "waiting_retry"
    assert state.keywords is None
    assert not any(stage.get("role") == "pair_category" for stage in state.stages.values())
    provider.generate = generate
    resumed = service.run(request)
    assert resumed.status == "selection_passed", resumed.reason


def test_category_selection_cannot_shorten_a_specific_phrase_to_a_generic_subterm(
    acquisition_session,
):
    service, _, provider, _, _ = prepared(acquisition_session)
    generate = provider.generate

    def shortened_category(**kwargs):
        response = generate(**kwargs)
        if "terms" in kwargs["schema"]["properties"]:
            # The original phrase is supported; its category-stage shortening is not adopted.
            response.output["terms"][1]["label"] = (
                "cloud sensor" if "source" in kwargs["data"] else "cloud"
            )
        return response

    provider.generate = shortened_category
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "waiting_retry", state.reason
    assert state.keywords is None
    assert not any(stage.get("role") == "pair_category" for stage in state.stages.values())


def test_missing_distinction_reason_is_repaired_but_never_cached(acquisition_session):
    service, _, provider, _, _ = prepared(acquisition_session)
    generate = provider.generate

    def no_distinction(**kwargs):
        response = generate(**kwargs)
        if "terms" in kwargs["schema"]["properties"]:
            for term in response.output["terms"]:
                term["distinction_reason"] = ""
        return response

    provider.generate = no_distinction
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "waiting_retry", state.reason
    assert state.ai_calls == 2
    assert state.stages == {} and state.keywords is None


def test_keyword_stages_receive_category_context_and_save_filter_decisions(
    acquisition_session, tmp_path
):
    import json

    service, _, provider, _, _ = prepared(acquisition_session)
    generate = provider.generate
    contexts = []

    def with_context(**kwargs):
        response = generate(**kwargs)
        if "terms" in kwargs["schema"]["properties"]:
            contexts.append(kwargs["data"]["category_context"])
            for term in response.output["terms"]:
                term["aliases"] = ["AI"]
        return response

    provider.generate = with_context
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "selection_passed", state.reason
    assert len(contexts) == 4
    assert all(context["category"] == "IoT" for context in contexts)
    assert all("判断" in context["excluded_generic_forms"] for context in contexts)
    stages = [
        v for v in state.stages.values() if v.get("role") in {"pair_keywords", "pair_category"}
    ]
    assert len(stages) == 4
    for stage in stages:
        assert all(term["aliases"] == [] for term in stage["output"]["terms"])
        assert all(d["removed_aliases"] == ["AI"] for d in stage["normalization"]["decisions"])
        assert stage["normalization"]["category_context"]["category"] == "IoT"
        if stage["role"] == "pair_category":
            assert all(
                d["document_count"] == 3 for d in stage["normalization"]["document_frequency"]
            )
    export_pair_run(acquisition_session, state.request.run_id, tmp_path)
    audit = json.loads((tmp_path / "audit.json").read_text())
    assert len(audit["keyword_document_frequency"]) == 3
    assert all(
        d["document_count"] == len(d["item_ids"]) == 3 for d in audit["keyword_document_frequency"]
    )


def test_negative_plan_records_rejection_without_adopting_unverified_products(acquisition_session):
    service, _, provider, _, _ = prepared(acquisition_session, comparable=False)
    generate = provider.generate

    def negative_with_unsupported_products(**kwargs):
        response = generate(**kwargs)
        if "axes" in kwargs["schema"]["properties"]:
            for p in response.output["products"]:
                p["organization"] = "unverified name"
                p["evidence"][0]["quote"] = "unverified quote"
        return response

    provider.generate = negative_with_unsupported_products
    state = service.run(PairDiscoveryRequest(source_key="fixture", initial_count=3))
    assert state.status == "exhausted", state.reason
    assert state.completed_pairs == 10
    assert all(not p["plan"]["products"] and not p["plan"]["axes"] for p in state.pair_results)
    assert all(
        p["reason"] == "pair_not_comparable_or_axes_insufficient" for p in state.pair_results
    )
    assert state.selected is None


def test_contact_feature_is_preserved_and_title_boilerplate_url_removed():
    doc = document(1, extra="\nお問い合わせ管理機能で通知する\nお問い合わせ先: 広報窓口")
    doc = doc.model_copy(update={"title": doc.title + " https://example.com/info"})
    clean, _ = embedding_text(doc)
    assert "お問い合わせ管理機能で通知する" in clean
    assert "広報窓口" not in clean
    assert "https://example.com/info" not in clean
