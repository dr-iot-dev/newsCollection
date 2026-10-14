"""Reused articles are not re-embedded; new identical chunks are billed just once."""

import json
import sqlite3
from pathlib import Path

import pytest

from app.infrastructure.extraction_embeddings import EmbeddingBatchResponse
from app.orchestration.extraction_distances import REPRESENTATION, digest
from app.orchestration.extraction_embedding_values import embed_article_values

MODEL = "text-embedding-3-small"
VALUE = [1.0] + [0.0] * 1535


def prepared(fid: str, text: str) -> dict:
    return {
        "f_id": fid,
        "article_id": fid,
        "title": fid,
        "url": "https://example.com/" + fid,
        "concept_count": 5,
        "domains": ["IoT"],
        "input_hash": digest(text),
        "text": text,
        "chunks": [{"text": text, "input_hash": digest(text), "weight": len(text.encode())}],
    }


class Provider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_many(self, texts) -> EmbeddingBatchResponse:
        self.calls.append(list(texts))
        return EmbeddingBatchResponse(tuple(tuple(VALUE) for _ in texts), MODEL, 20, "test", 1)


def test_existing_article_and_chunks_reused_and_exact_costs(tmp_path: Path) -> None:
    previous = tmp_path / "previous.sqlite"
    with sqlite3.connect(previous) as db:
        db.execute("CREATE TABLE article_values(model TEXT,input_hash TEXT,value_json TEXT)")
        db.execute("CREATE TABLE embedding_chunks(model TEXT,input_hash TEXT,value_json TEXT)")
        db.execute(
            "INSERT INTO article_values VALUES (?,?,?)", (MODEL, digest("old"), json.dumps(VALUE))
        )
        db.execute(
            "INSERT INTO embedding_chunks VALUES (?,?,?)",
            (MODEL, digest("partial"), json.dumps(VALUE)),
        )
    run = {
        "run_key": "fixture",
        "model": MODEL,
        "representation": REPRESENTATION,
        "articles": [
            prepared("F001", "old"),
            prepared("F002", "new"),
            prepared("F003", "new"),
            prepared("F004", "partial"),
        ],
    }
    provider = Provider()
    output = tmp_path / "result"
    summary = embed_article_values(run, output, provider, previous)
    assert provider.calls == [["new"]]
    assert summary["reused_articles"] == 1
    assert summary["article_count"] == 4
    assert summary["embedding_tokens"] == 20
    values = json.loads((output / "article-values.json").read_text())["articles"]
    assert len(values) == 4
    assert values[0]["value"] == VALUE
    assert values[0]["embedding_reused"] is True
    price = json.loads((output / "cost-estimate.json").read_text())
    assert price["estimated_api_cost_usd"] == pytest.approx(20 * 0.02 / 1_000_000)
    assert price["mean_per_target_article_usd"] == pytest.approx(
        price["estimated_api_cost_usd"] / 4
    )
    before = previous.read_bytes()
    embed_article_values(run, output, provider, previous)
    assert provider.calls == [["new"]]
    assert previous.read_bytes() == before


def test_cache_does_not_cover_changed_text(tmp_path: Path) -> None:
    previous = tmp_path / "previous.sqlite"
    with sqlite3.connect(previous) as db:
        db.execute("CREATE TABLE article_values(model TEXT,input_hash TEXT,value_json TEXT)")
        db.execute("CREATE TABLE embedding_chunks(model TEXT,input_hash TEXT,value_json TEXT)")
        db.execute(
            "INSERT INTO article_values VALUES (?,?,?)", (MODEL, digest("old"), json.dumps(VALUE))
        )
    provider = Provider()
    run = {
        "run_key": "changed",
        "model": MODEL,
        "representation": REPRESENTATION,
        "articles": [prepared("F001", "changed")],
    }
    summary = embed_article_values(run, tmp_path / "result", provider, previous)
    assert provider.calls == [["changed"]]
    assert summary["reused_articles"] == 0
