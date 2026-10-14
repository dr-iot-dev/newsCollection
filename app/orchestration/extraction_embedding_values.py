"""Embed a frozen Extraction cohort, reusing unchanged article and chunk values."""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.core.comparison_pair_discovery import aggregate_vectors
from app.infrastructure.comparison_retrieval import Embedding, cosine
from app.orchestration.extraction_distances import REPRESENTATION, BatchEmbedder

EMBEDDING_PRICE_USD_PER_MILLION = 0.02
EMBEDDING_PRICE_SOURCE = "https://developers.openai.com/api/docs/models/text-embedding-3-small"


def embed_article_values(
    run: dict[str, Any],
    output: Path,
    provider: BatchEmbedder,
    reuse_database: Path | None = None,
    progress: Callable[[dict[str, Any]], None] = lambda _: None,
) -> dict[str, Any]:
    """No pairwise ranking; every selected article receives one normalized value."""
    if run["model"] != "text-embedding-3-small" or run["representation"] != REPRESENTATION:
        raise ValueError("cost accounting currently requires text-embedding-3-small")
    output.mkdir(parents=True, exist_ok=True)
    reused: dict[str, list[float]] = {}
    previous_ids: dict[str, str] = {}
    chunk_cache: dict[str, list[float]] = {}
    if reuse_database:
        if not reuse_database.is_file():
            raise ValueError("reuse database does not exist")
        filename = reuse_database.resolve().as_posix()
        # SQLite needs an empty URI authority for Windows UNC network paths.
        uri = "file:" + ("//" if filename.startswith("//") else "") + quote(filename, safe="/:")
        with sqlite3.connect(uri + "?mode=ro", uri=True) as previous:
            columns = {row[1] for row in previous.execute("PRAGMA table_info(article_values)")}
            if {"article_id", "f_id"} <= columns:
                previous_ids = dict(
                    previous.execute(
                        "SELECT article_id,f_id FROM article_values WHERE model=?", (run["model"],)
                    )
                )
            for key, encoded in previous.execute(
                "SELECT input_hash,value_json FROM article_values WHERE model=?", (run["model"],)
            ):
                value = json.loads(encoded)
                cosine(
                    Embedding("openai", run["model"], REPRESENTATION, tuple(value)),
                    Embedding("openai", run["model"], REPRESENTATION, tuple(value)),
                )
                reused[key] = value
            chunk_cache = {
                key: json.loads(value)
                for key, value in previous.execute(
                    "SELECT input_hash,value_json FROM embedding_chunks WHERE model=?",
                    (run["model"],),
                )
            }
    selected = run["articles"]
    cached_article_count = sum(article["input_hash"] in reused for article in selected)
    with sqlite3.connect(output / "article-values.sqlite") as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS embedding_chunks (
                model TEXT NOT NULL,input_hash TEXT NOT NULL,value_json TEXT NOT NULL,
                PRIMARY KEY(model,input_hash)
            );
            CREATE TABLE IF NOT EXISTS article_values (
                run_key TEXT NOT NULL,f_id TEXT NOT NULL,article_id TEXT NOT NULL,
                title TEXT NOT NULL,input_hash TEXT NOT NULL,model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,value_json TEXT NOT NULL,
                PRIMARY KEY(run_key,f_id)
            );
            CREATE TABLE IF NOT EXISTS embedding_requests (
                run_key TEXT NOT NULL,request_id TEXT,tokens INTEGER NOT NULL,latency_ms INTEGER,
                input_hashes_json TEXT NOT NULL,created_at TEXT NOT NULL
            );
        """)
        db.executemany(
            "INSERT OR IGNORE INTO embedding_chunks VALUES (?,?,?)",
            [(run["model"], key, json.dumps(value)) for key, value in chunk_cache.items()],
        )
        chunk_cache = {
            key: json.loads(value)
            for key, value in db.execute(
                "SELECT input_hash,value_json FROM embedding_chunks WHERE model=?", (run["model"],)
            )
        }
        db.commit()
        chunks = {
            chunk["input_hash"]: chunk["text"]
            for article in selected
            if article["input_hash"] not in reused
            for chunk in article["chunks"]
        }
        missing = [(key, text) for key, text in chunks.items() if key not in chunk_cache]
        progress({"reused_articles": cached_article_count, "new_chunks": len(missing)})
        for start in range(0, len(missing), 16):
            batch = missing[start : start + 16]
            response = provider.embed_many([text for _, text in batch])
            if response.model != run["model"] or len(response.values) != len(batch):
                raise ValueError("embedding batch identity mismatch")
            if type(response.tokens) is not int or response.tokens < 0:
                raise ValueError("embedding provider did not return token usage")
            for (key, _), value in zip(batch, response.values, strict=True):
                vector = Embedding("openai", run["model"], REPRESENTATION, value)
                cosine(vector, vector)
                if len(value) != 1536:
                    raise ValueError("unexpected embedding dimensions")
                chunk_cache[key] = list(value)
                db.execute(
                    "INSERT INTO embedding_chunks VALUES (?,?,?)",
                    (run["model"], key, json.dumps(value)),
                )
            db.execute(
                "INSERT INTO embedding_requests VALUES (?,?,?,?,?,?)",
                (
                    run["run_key"],
                    response.request_id,
                    response.tokens,
                    response.latency_ms,
                    json.dumps([key for key, _ in batch]),
                    datetime.now(UTC).isoformat(),
                ),
            )
            db.commit()
            progress({"embedded_chunks": min(start + 16, len(missing)), "new_chunks": len(missing)})
        articles = []
        for article in selected:
            cached = article["input_hash"] in reused
            value = (
                reused[article["input_hash"]]
                if cached
                else aggregate_vectors(
                    [chunk_cache[c["input_hash"]] for c in article["chunks"]],
                    [c["weight"] for c in article["chunks"]],
                )
            )
            if len(value) != 1536:
                raise ValueError("unexpected article vector dimensions")
            vector = Embedding("openai", run["model"], REPRESENTATION, tuple(value))
            cosine(vector, vector)
            row = {k: v for k, v in article.items() if k not in {"text", "chunks"}}
            if article["article_id"] in previous_ids:
                row["previous_f_id"] = previous_ids[article["article_id"]]
            row.update(
                model=run["model"],
                dimensions=len(value),
                value=list(value),
                embedding_reused=cached,
            )
            articles.append(row)
            db.execute(
                "INSERT OR REPLACE INTO article_values VALUES (?,?,?,?,?,?,?,?)",
                (
                    run["run_key"],
                    article["f_id"],
                    article["article_id"],
                    article["title"],
                    article["input_hash"],
                    run["model"],
                    len(value),
                    json.dumps(value),
                ),
            )
        db.commit()
        requests, tokens = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(tokens),0) FROM embedding_requests WHERE run_key=?",
            (run["run_key"],),
        ).fetchone()
    cost = tokens * EMBEDDING_PRICE_USD_PER_MILLION / 1_000_000
    newly_embedded_articles = len(articles) - cached_article_count
    summary = {k: v for k, v in run.items() if k not in {"articles", "pair_count", "metric"}}
    summary.update(
        article_count=len(articles),
        dimensions=1536,
        reused_articles=cached_article_count,
        newly_embedded_articles=newly_embedded_articles,
        embedding_requests=requests,
        embedding_tokens=tokens,
        completed_at=datetime.now(UTC).isoformat(),
    )
    pricing = {
        "run_key": run["run_key"],
        "currency": "USD",
        "model": run["model"],
        "pricing_source": EMBEDDING_PRICE_SOURCE,
        "price_checked_date": "2026-10-13",
        "usd_per_million_input_tokens": EMBEDDING_PRICE_USD_PER_MILLION,
        "billable_input_tokens": tokens,
        "estimated_api_cost_usd": cost,
        "article_count": len(articles),
        "reused_articles": cached_article_count,
        "newly_embedded_articles": newly_embedded_articles,
        "mean_per_target_article_usd": cost / len(articles),
        "mean_per_newly_embedded_article_usd": (
            cost / newly_embedded_articles if newly_embedded_articles else 0
        ),
        "scope": "current_run_embeddings_API_only; reused_values_have_zero_incremental_cost",
    }
    for filename, data in [
        (
            "article-values.json",
            {
                "model": run["model"],
                "representation": REPRESENTATION,
                "articles": articles,
                "cohort": {
                    key: run[key]
                    for key in (
                        "selection",
                        "title_filter_policy",
                        "title_exclusion_word_count",
                        "allowed_domains",
                        "required_release_type",
                        "F_count",
                        "E_count",
                    )
                    if key in run
                },
            },
        ),
        ("embedding-summary.json", summary),
        ("cost-estimate.json", pricing),
    ]:
        (output / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    return summary
