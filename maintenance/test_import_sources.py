"""Administration-only source migration test, outside the application test context."""

import json
import sqlite3

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine_for, initialize
from app.models import Article
from maintenance.import_sources import import_legacy_sources


def test_saved_html_is_imported_readonly_after_rechecking_conditions(tmp_path):
    corpus, snapshots = tmp_path / "corpus.sqlite", tmp_path / "audit.sqlite"
    url = "https://prtimes.jp/main/html/rd/p/000000001.000000001.html"
    metadata = {
        "@type": "NewsArticle",
        "headline": "IoT 製品",
        "datePublished": "2026-10-15",
        "author": {"@type": "Organization", "name": "Example"},
    }
    html = (
        '<script type="application/ld+json">' + json.dumps(metadata) + "</script>"
        '<h1>IoT 製品</h1><div id="press-release-body">IoT</div>'
        '<a href="/main/html/searchrlp/company_id/1">Example</a>'
        '<a href="/main/html/searchrlp/release_type_id/01/">商品サービス</a>'
    )
    with sqlite3.connect(corpus) as old:
        old.execute("CREATE TABLE term_articles(article_id TEXT,url TEXT)")
        old.execute("INSERT INTO term_articles VALUES(?,?)", (url, url))
    with sqlite3.connect(snapshots) as old:
        old.execute("CREATE TABLE raw_snapshots(final_url TEXT,body_text TEXT,fetched_at TEXT)")
        old.execute("INSERT INTO raw_snapshots VALUES(?,?,?)", (url, html, "2026-10-15"))
    before = (corpus.read_bytes(), snapshots.read_bytes())
    engine = engine_for("sqlite:///" + (tmp_path / "pipeline.sqlite").as_posix())
    initialize(engine)
    with Session(engine) as session:
        result = import_legacy_sources(session, corpus, snapshots, [])
        assert result == {"accepted": 1, "excluded": 0, "missing_snapshot": 0}
        assert session.scalar(select(Article)).body == "IoT"
    engine.dispose()
    assert before == (corpus.read_bytes(), snapshots.read_bytes())
