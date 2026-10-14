"""Freeze E/F, assign one semantic vector to each F article and rank every unordered pair."""

import csv
import hashlib
import json
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Protocol

from app.core.comparison_pair_discovery import aggregate_vectors
from app.infrastructure.comparison_embeddings import embedding_chunks
from app.infrastructure.comparison_retrieval import Embedding, cosine
from app.infrastructure.extraction_distance_report import distance_report_html
from app.infrastructure.extraction_embeddings import EmbeddingBatchResponse
from app.infrastructure.term_corpus import TermCorpusStore

REPRESENTATION = "stored-title-and-full-body-utf8-weighted-v1"


class BatchEmbedder(Protocol):
    def embed_many(self, texts: Sequence[str]) -> EmbeddingBatchResponse: ...


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def prepare_distance_analysis(
    database: Path,
    corpus: str,
    counts_file: Path,
    output: Path,
    model: str = "text-embedding-3-small",
) -> dict[str, Any]:
    payload = json.loads(counts_file.read_text(encoding="utf-8-sig"))
    source = payload["articles"]
    if payload["corpus"] != corpus or payload["article_count"] != len(source):
        raise ValueError("E snapshot metadata mismatch")
    with TermCorpusStore(database) as store:
        current = store.count_candidates(corpus, payload["vocabulary_hash"])
        expected = {row["article_id"]: row["concept_count"] for row in source}
        if len(expected) != len(source) or expected != {
            row["article_id"]: row["concept_count"] for row in current
        }:
            raise ValueError("E differs from the current database counts")
        articles = {article.article_id: article for article in store.articles(corpus)}
    selected = sorted(
        (row for row in source if row["concept_count"] > 4),
        key=lambda row: (-row["concept_count"], row["article_id"]),
    )
    if len(selected) < 2:
        raise ValueError("F must contain at least two articles")
    prepared = []
    for index, row in enumerate(selected, 1):
        article = articles[row["article_id"]]
        text = article.title + "\n\n" + article.body
        prepared.append(
            {
                "f_id": f"F{index:03d}",
                "article_id": article.article_id,
                "title": article.title,
                "url": row["url"],
                "concept_count": row["concept_count"],
                "domains": row["domains"],
                "text": text,
                "input_hash": digest(text),
                "chunks": [
                    {"text": chunk, "input_hash": digest(chunk), "weight": len(chunk.encode())}
                    for chunk in embedding_chunks(text)
                ],
            }
        )
    signature = json.dumps(
        {
            "model": model,
            "representation": REPRESENTATION,
            "vocabulary_hash": payload["vocabulary_hash"],
            "E": expected,
            "F": [(r["article_id"], r["input_hash"]) for r in prepared],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    run = {
        "run_key": digest(signature),
        "E_count": len(source),
        "F_count": len(prepared),
        "removed_from_E": len(source) - len(prepared),
        "selection": "concept_count > 4",
        "model": model,
        "representation": REPRESENTATION,
        "metric": "one_minus_cosine",
        "pair_count": len(prepared) * (len(prepared) - 1) // 2,
        "source_database": str(database),
        "source_counts": str(counts_file),
        "source_vocabulary_hash": payload["vocabulary_hash"],
        "articles": prepared,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "embedding-input.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "group-F.json").write_text(
        json.dumps(
            {
                **{k: v for k, v in run.items() if k != "articles"},
                "articles": [
                    {k: v for k, v in r.items() if k not in {"text", "chunks"}} for r in prepared
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return run


def calculate_distances(
    run: dict[str, Any],
    output: Path,
    provider: BatchEmbedder,
    progress: Callable[[dict[str, Any]], None] = lambda _: None,
) -> dict[str, Any]:
    with sqlite3.connect(output / "article-values.sqlite") as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS embedding_chunks (
                model TEXT NOT NULL, input_hash TEXT NOT NULL, value_json TEXT NOT NULL,
                PRIMARY KEY(model,input_hash)
            );
            CREATE TABLE IF NOT EXISTS embedding_requests (
                run_key TEXT NOT NULL,request_id TEXT,tokens INTEGER,latency_ms INTEGER,
                input_hashes_json TEXT NOT NULL,created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS article_values (
                run_key TEXT NOT NULL,f_id TEXT NOT NULL,article_id TEXT NOT NULL,
                title TEXT NOT NULL,input_hash TEXT NOT NULL,model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,value_json TEXT NOT NULL,
                PRIMARY KEY(run_key,f_id)
            );
            CREATE TABLE IF NOT EXISTS pair_distances (
                run_key TEXT NOT NULL,rank INTEGER NOT NULL,left_id TEXT NOT NULL,
                right_id TEXT NOT NULL,distance REAL NOT NULL,PRIMARY KEY(run_key,rank)
            );
        """)
        chunks = {
            chunk["input_hash"]: chunk["text"]
            for article in run["articles"]
            for chunk in article["chunks"]
        }
        cached = {
            key: json.loads(value)
            for key, value in db.execute(
                "SELECT input_hash,value_json FROM embedding_chunks WHERE model=?", (run["model"],)
            )
        }
        missing = [(key, text) for key, text in chunks.items() if key not in cached]
        for offset in range(0, len(missing), 16):
            batch = missing[offset : offset + 16]
            response = provider.embed_many([text for _, text in batch])
            if response.model != run["model"] or len(response.values) != len(batch):
                raise ValueError("embedding batch identity mismatch")
            for (key, _), values in zip(batch, response.values, strict=True):
                vector = Embedding("openai", response.model, REPRESENTATION, values)
                cosine(vector, vector)
                cached[key] = list(values)
                db.execute(
                    "INSERT INTO embedding_chunks VALUES (?,?,?)",
                    (run["model"], key, json.dumps(values)),
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
            progress(
                {
                    "embedded_chunks": min(offset + len(batch), len(missing)),
                    "new_chunks": len(missing),
                    "unique_chunks": len(chunks),
                }
            )
        vectors: dict[str, Embedding] = {}
        article_values = []
        for article in run["articles"]:
            value = aggregate_vectors(
                [cached[c["input_hash"]] for c in article["chunks"]],
                [c["weight"] for c in article["chunks"]],
            )
            vector = Embedding("openai", run["model"], REPRESENTATION, value)
            cosine(vector, vector)
            vectors[article["f_id"]] = vector
            row = {k: v for k, v in article.items() if k not in {"text", "chunks"}}
            row.update(model=run["model"], dimensions=len(value), value=list(value))
            article_values.append(row)
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
        rows = sorted(
            (
                {"left_id": a, "right_id": b, "distance": 1 - cosine(vectors[a], vectors[b])}
                for a, b in combinations(sorted(vectors), 2)
            ),
            key=lambda row: (row["distance"], row["left_id"], row["right_id"]),
        )
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
            db.execute(
                "INSERT OR REPLACE INTO pair_distances VALUES (?,?,?,?,?)",
                (run["run_key"], rank, row["left_id"], row["right_id"], row["distance"]),
            )
        db.commit()
        dimensions = {len(v.values) for v in vectors.values()}
        if len(dimensions) != 1 or len(rows) != run["pair_count"]:
            raise ValueError("vector or pair coverage mismatch")
        requests, tokens = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(tokens),0) FROM embedding_requests WHERE run_key=?",
            (run["run_key"],),
        ).fetchone()
    summary = {k: v for k, v in run.items() if k != "articles"}
    summary.update(
        dimensions=next(iter(dimensions)),
        embedding_requests=requests,
        embedding_tokens=tokens,
        unique_chunks=len(chunks),
        min_distance=rows[0]["distance"],
        max_distance=rows[-1]["distance"],
        completed_at=datetime.now(UTC).isoformat(),
    )
    (output / "article-values.json").write_text(
        json.dumps(
            {
                "model": run["model"],
                "representation": REPRESENTATION,
                "articles": article_values,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "pair-distances.json").write_text(
        json.dumps({"summary": summary, "pairs": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    by_id = {row["f_id"]: row for row in article_values}
    with (output / "pair-distances.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["rank", "distance", "article_A", "title_A", "article_B", "title_B", "url_A", "url_B"]
        )
        for row in rows:
            a, b = by_id[row["left_id"]], by_id[row["right_id"]]
            writer.writerow(
                [
                    row["rank"],
                    row["distance"],
                    a["f_id"],
                    a["title"],
                    b["f_id"],
                    b["title"],
                    a["url"],
                    b["url"],
                ]
            )
    (output / "pair-distances.html").write_text(
        distance_report_html(summary, article_values, rows), encoding="utf-8"
    )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary
