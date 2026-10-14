"""E/F threshold, real pair mathematics, resumable vectors and provider coverage."""

import json
import math

import httpx
import pytest

from app.contracts.discovery_search_vocabulary_v2 import DiscoveryArticle
from app.infrastructure.extraction_distance_report import distance_report_html
from app.infrastructure.extraction_embeddings import (
    EmbeddingBatchResponse,
    OpenAIEmbeddingBatchProvider,
)
from app.infrastructure.term_corpus import TermCorpusStore
from app.orchestration.extraction_distances import calculate_distances, prepare_distance_analysis
from tests.unit.test_discovery_search_vocabulary import vocabulary


def prepare(tmp_path):
    database = tmp_path / "source.sqlite"
    with TermCorpusStore(database) as store:
        store.create_corpus("test", "AI")
        for key in ("A", "B", "C", "D"):
            body = "監視 管理 連携 価格 API" if key != "D" else "監視 管理 連携 価格"
            title = "AI same" if key in ("A", "B") else "AI " + key
            store.import_article("test", DiscoveryArticle(article_id=key, title=title, body=body))
        key = store.save_vocabulary(vocabulary())
        rows = store.count_candidates("test", key)
    counts = tmp_path / "counts.json"
    counts.write_text(
        json.dumps(
            {"articles": rows, "article_count": len(rows), "corpus": "test", "vocabulary_hash": key}
        ),
        encoding="utf-8",
    )
    return prepare_distance_analysis(database, "test", counts, tmp_path / "results")


class Provider:
    def __init__(self):
        self.calls = 0

    def embed_many(self, texts):
        self.calls += 1
        return EmbeddingBatchResponse(
            tuple((0.0, 1.0) if "AI C" in t else (1.0, 0.0) for t in texts),
            "text-embedding-3-small",
            10,
            "test-request",
            1,
        )


def test_threshold_all_pairs_values_and_cache_resume(tmp_path):
    run = prepare(tmp_path)
    assert run["E_count"] == 4 and run["F_count"] == 3 and run["removed_from_E"] == 1
    assert all(r["concept_count"] > 4 for r in run["articles"])
    provider = Provider()
    summary = calculate_distances(run, tmp_path / "results", provider)
    assert provider.calls == 1
    assert summary["pair_count"] == 3 and summary["dimensions"] == 2
    pairs = json.loads((tmp_path / "results/pair-distances.json").read_text())["pairs"]
    assert [p["distance"] for p in pairs] == [0.0, 1.0, 1.0]
    assert pairs[0]["left_id"] == "F001" and pairs[0]["right_id"] == "F002"
    values = json.loads((tmp_path / "results/article-values.json").read_text())["articles"]
    assert all(math.isclose(math.hypot(*r["value"]), 1) for r in values)
    assert (tmp_path / "results/article-values.sqlite").exists()
    calculate_distances(run, tmp_path / "results", provider)
    assert provider.calls == 1


def test_changed_e_counts_rejected_before_embedding(tmp_path):
    prepare(tmp_path)
    p = tmp_path / "counts.json"
    payload = json.loads(p.read_text())
    payload["articles"][0]["concept_count"] = 20
    p.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="E differs"):
        prepare_distance_analysis(tmp_path / "source.sqlite", "test", p, tmp_path / "results")


def test_all_utf8_text_retained_without_truncation(tmp_path):
    run = prepare(tmp_path)
    for article in run["articles"]:
        assert "".join(c["text"] for c in article["chunks"]) == article["text"]
        assert sum(c["weight"] for c in article["chunks"]) == len(article["text"].encode())


def test_zero_vector_never_produces_distances(tmp_path):
    run = prepare(tmp_path)

    class Zero:
        def embed_many(self, texts):
            return EmbeddingBatchResponse(
                tuple((0.0, 0.0) for _ in texts), run["model"], 1, None, 1
            )

    with pytest.raises(ValueError, match="Zero embedding"):
        calculate_distances(run, tmp_path / "results", Zero())
    assert not (tmp_path / "results/pair-distances.json").exists()


def test_report_escapes_source_titles_and_keeps_every_pair():
    html = distance_report_html(
        {"F_count": 2},
        [{"f_id": "F001", "title": "</script><script>alert(1)</script>"}],
        [{"left_id": "F001", "right_id": "F002", "distance": 0.1}],
    )
    assert "</script><script>alert(1)</script>" not in html
    assert "text-overflow:ellipsis" in html
    assert "\\u003c" in html


def test_batch_provider_binds_unsorted_indices_to_inputs():
    def respond(request):
        payload = json.loads(request.content)
        assert payload["input"] == ["one", "two"]
        return httpx.Response(
            200,
            json={
                "model": "test",
                "data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}],
                "usage": {"total_tokens": 5},
            },
        )

    provider = OpenAIEmbeddingBatchProvider(
        "not-a-real-key", "test", transport=httpx.MockTransport(respond)
    )
    result = provider.embed_many(["one", "two"])
    assert result.values == ((1, 0), (0, 1)) and result.tokens == 5


@pytest.mark.parametrize("texts", [[""], ["a"] * 17, ["あ" * 2001]])
def test_batch_provider_limits_are_checked_before_network(texts):
    provider = OpenAIEmbeddingBatchProvider("not-a-real-key", "test")
    with pytest.raises(ValueError, match="invalid embedding batch"):
        provider.embed_many(texts)
