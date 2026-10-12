"""DB persistence and SQL counting for a 200+ article corpus."""

import json

from typer.testing import CliRunner

from app.cli import app
from app.contracts.discovery_search_vocabulary_v2 import DiscoveryArticle
from app.infrastructure.term_corpus import TermCorpusStore
from tests.unit.test_discovery_search_vocabulary import vocabulary


def test_database_counts_all_220_articles_with_alias_deduplication_and_boundaries(tmp_path):
    database = tmp_path / "articles.sqlite"
    with TermCorpusStore(database) as store:
        store.create_corpus("iot", "IoT")
        for i in range(220):
            body = "監視、監視、モニタリング、ＡＰＩ連携。" if i == 0 else "rapidapiの紹介。"
            store.import_article(
                "iot", DiscoveryArticle(article_id=str(i), title=f"IoT記事{i}", body=body)
            )
        key = store.save_vocabulary(vocabulary())
    # Reopen the database: results come from saved rows and registered terms, not input objects.
    with TermCorpusStore(database) as store:
        traced = []
        store.connection.set_trace_callback(traced.append)
        rows = store.count_candidates("iot", key)
        assert len(rows) == store.article_count("iot") == 220
        hit = rows[0]
        assert hit["article_id"] == "0"
        assert hit["concept_count"] == 3
        assert hit["matched_term_count"] == 4
        assert set(hit["matched_terms"]) == {"監視", "モニタリング", "API", "連携"}
        assert sum(row["concept_count"] == 0 for row in rows) == 219
        assert any("COUNT(DISTINCT m.concept_id)" in query for query in traced)


def test_import_update_does_not_duplicate_articles_or_leak_between_corpora(tmp_path):
    with TermCorpusStore(tmp_path / "articles.sqlite") as store:
        for corpus in ("one", "two"):
            store.create_corpus(corpus, corpus)
        store.import_article("one", DiscoveryArticle(article_id="A", title="IoT価格", body="価格"))
        store.import_article(
            "one", DiscoveryArticle(article_id="A", title="IoT更新後", body="監視")
        )
        store.import_article(
            "two", DiscoveryArticle(article_id="A", title="IoT別集合", body="価格")
        )
        key = store.save_vocabulary(vocabulary())
        assert store.article_count("one") == 1
        assert store.count_candidates("one", key)[0]["matched_terms"] == ["監視"]
        assert store.count_candidates("two", key)[0]["matched_terms"] == ["価格"]


def test_cli_import_then_database_count_with_full_table_and_minimum(tmp_path):
    articles = tmp_path / "articles.json"
    articles.write_text(
        json.dumps(
            [
                {
                    "article_id": str(i),
                    "title": f"IoT記事{i}",
                    "body": "価格" if i == 0 else "企業紹介",
                }
                for i in range(200)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    vocab = tmp_path / "vocabulary.json"
    vocab.write_text(vocabulary().model_dump_json(), encoding="utf-8")
    database = tmp_path / "corpus.sqlite"
    runner = CliRunner()
    imported = runner.invoke(
        app,
        [
            "extraction",
            "import",
            "--database",
            str(database),
            "--corpus",
            "iot",
            "--articles",
            str(articles),
        ],
    )
    assert imported.exit_code == 0, imported.output
    assert json.loads(imported.output)["stored_articles"] == 200
    output = tmp_path / "counts"
    counted = runner.invoke(
        app,
        [
            "extraction",
            "count",
            "--database",
            str(database),
            "--corpus",
            "iot",
            "--vocabulary",
            str(vocab),
            "--output",
            str(output),
        ],
    )
    assert counted.exit_code == 0, counted.output
    saved = json.loads((output / "counts.json").read_text(encoding="utf-8"))
    assert saved["article_count"] == len(saved["articles"]) == 200
    assert saved["execution"] == "database_sql"
    assert saved["articles"][0]["concept_count"] == 1
    assert len((output / "counts.md").read_text(encoding="utf-8").splitlines()) == 202
    assert (output / "counts.csv").exists()
    rejected = runner.invoke(
        app,
        [
            "extraction",
            "count",
            "--database",
            str(database),
            "--corpus",
            "iot",
            "--vocabulary",
            str(vocab),
            "--minimum-articles",
            "201",
        ],
    )
    assert rejected.exit_code == 1
    assert "eligible articles 200 < minimum 201" in rejected.output


def test_legacy_exclusion_flags_prevent_loading_and_candidate_search(tmp_path):
    from app.contracts.discovery_search_vocabulary_v2 import normalized_text
    from app.core.discovery_search_vocabulary import term_matches

    database = tmp_path / "legacy.sqlite"
    with TermCorpusStore(database) as store:
        store.create_corpus("iot", "IoT")
        store.import_article(
            "iot", DiscoveryArticle(article_id="allowed", title="IoT製品情報", body="監視")
        )
        # Simulate an article archived before the title filter was installed.
        store.connection.execute(
            "INSERT INTO term_articles "
            "(corpus_id,article_id,url,title,body,normalized_title,normalized_body,"
            "content_hash,imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "iot",
                "blocked",
                "",
                "製品の提供開始",
                "DO_NOT_SEARCH 監視 価格",
                "製品の提供開始",
                normalized_text("DO_NOT_SEARCH 監視 価格"),
                "old",
                "old",
            ),
        )
        store.connection.commit()
        key = store.save_vocabulary(vocabulary())
    with TermCorpusStore(database) as store:
        flagged = store.connection.execute(
            "SELECT title_excluded,title_exclusion_terms FROM term_articles "
            "WHERE article_id='blocked'"
        ).fetchone()
        assert flagged[0] == 1
        assert json.loads(flagged[1]) == ["開始"]
        assert store.stored_article_count("iot") == 2
        assert store.article_count("iot") == 1
        assert [a.article_id for a in store.articles("iot")] == ["allowed"]
        searched = []

        def inspect_match(term, text):
            searched.append(text)
            assert "do_not_search" not in text
            return term_matches(term, text)

        store.connection.create_function("phrase_match", 2, inspect_match, deterministic=True)
        rows = store.count_candidates("iot", key)
        assert len(rows) == 1 and rows[0]["article_id"] == "allowed"
        assert searched
        assert store.excluded_articles("iot")[0]["matched_exclusion_terms"] == ["開始"]


def test_cli_excludes_title_before_reading_or_validating_body(tmp_path):
    articles = tmp_path / "input.json"
    articles.write_text(
        json.dumps(
            [
                {"article_id": "good", "title": "IoTの新しいAPI", "body": "API"},
                {"article_id": "bad", "title": "APIを公開"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    database = tmp_path / "corpus.sqlite"
    result = CliRunner().invoke(
        app,
        [
            "extraction",
            "import",
            "--database",
            str(database),
            "--corpus",
            "iot",
            "--articles",
            str(articles),
        ],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["stored_articles"] == summary["eligible_articles"] == 1
    assert summary["excluded_input_articles"] == 1
    with TermCorpusStore(database) as store:
        assert not store.has_article("iot", "bad")
        assert store.excluded_articles("iot")[0]["article_id"] == "bad"


def test_flag_alone_blocks_an_article_from_database_search(tmp_path):
    with TermCorpusStore(tmp_path / "articles.sqlite") as store:
        store.create_corpus("iot", "IoT")
        store.import_article(
            "iot", DiscoveryArticle(article_id="A", title="IoT製品情報", body="監視")
        )
        store.connection.execute("UPDATE term_articles SET title_excluded=1")
        store.connection.commit()
        key = store.save_vocabulary(vocabulary())
        assert store.article_count("iot") == 0
        assert store.articles("iot") == ()
        assert store.count_candidates("iot", key) == []


def test_title_update_through_import_rechecks_exclusion_policy(tmp_path):
    with TermCorpusStore(tmp_path / "articles.sqlite") as store:
        store.create_corpus("iot", "IoT")
        assert store.import_article(
            "iot", DiscoveryArticle(article_id="A", title="IoT製品情報", body="監視")
        )
        assert not store.import_article(
            "iot", DiscoveryArticle(article_id="A", title="API公開", body="API")
        )
        assert store.article_count("iot") == 0
        assert store.import_article(
            "iot", DiscoveryArticle(article_id="A", title="IoTの新しいAPI", body="API")
        )
        assert store.article_count("iot") == 1
        assert store.excluded_articles("iot") == []


def test_updated_exclusion_title_is_preserved_after_reopening_database(tmp_path):
    database = tmp_path / "articles.sqlite"
    with TermCorpusStore(database) as store:
        store.create_corpus("iot", "IoT")
        store.import_article(
            "iot", DiscoveryArticle(article_id="A", title="IoT製品情報", body="監視")
        )
        store.record_title_exclusion("iot", "A", "APIを公開")
    with TermCorpusStore(database) as store:
        assert store.article_count("iot") == 0
        assert store.excluded_articles("iot")[0]["title"] == "APIを公開"


def test_domain_filter_rejects_legacy_general_article_before_candidate_matching(tmp_path):
    from app.core.discovery_search_vocabulary import term_matches

    database = tmp_path / "legacy.sqlite"
    with TermCorpusStore(database) as store:
        store.create_corpus("iot", "IoT")
        store.import_article(
            "iot", DiscoveryArticle(article_id="good", title="IoT製品", body="監視")
        )
        store.connection.execute(
            "INSERT INTO term_articles "
            "(corpus_id,article_id,url,title,body,normalized_title,normalized_body,"
            "content_hash,imported_at) "
            "VALUES ('iot','bad','','一般商品','DO_NOT_SEARCH 監視',"
            "'一般商品','do_not_search 監視','old','old')"
        )
        store.connection.commit()
        key = store.save_vocabulary(vocabulary())
    with TermCorpusStore(database) as store:

        def inspect(term, text):
            assert "do_not_search" not in text
            return term_matches(term, text)

        store.connection.create_function("phrase_match", 2, inspect, deterministic=True)
        assert [r["article_id"] for r in store.count_candidates("iot", key)] == ["good"]
        assert [r.article_id for r in store.articles("iot")] == ["good"]
        assert store.excluded_articles("iot")[0]["exclusion_reason"] == "outside_ai_iot"


def test_domain_flag_and_reimport_control_search_eligibility(tmp_path):
    with TermCorpusStore(tmp_path / "articles.sqlite") as store:
        store.create_corpus("iot", "IoT")
        assert store.import_article(
            "iot", DiscoveryArticle(article_id="A", title="IoT製品", body="監視")
        )
        store.connection.execute("UPDATE term_articles SET domain_eligible=0")
        store.connection.commit()
        key = store.save_vocabulary(vocabulary())
        assert store.article_count("iot") == 0
        assert store.count_candidates("iot", key) == []
        assert store.articles("iot") == ()
        assert not store.import_article(
            "iot", DiscoveryArticle(article_id="A", title="一般商品", body="監視")
        )
        assert store.excluded_articles("iot")[0]["exclusion_reason"] == "outside_ai_iot"
        assert store.import_article(
            "iot", DiscoveryArticle(article_id="A", title="AI製品", body="監視")
        )
        assert store.article_count("iot") == 1
        assert store.excluded_articles("iot") == []
        assert store.count_candidates("iot", key)[0]["domains"] == ["AI"]


def test_cli_domain_rejection_does_not_save_general_article_body(tmp_path):
    articles = tmp_path / "articles.json"
    articles.write_text(
        json.dumps(
            [
                {"article_id": "good", "title": "AI製品", "body": "監視"},
                {"article_id": "bad", "title": "一般商品", "body": "価格"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    database = tmp_path / "articles.sqlite"
    result = CliRunner().invoke(
        app,
        [
            "extraction",
            "import",
            "--database",
            str(database),
            "--corpus",
            "iot",
            "--articles",
            str(articles),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["domain_excluded_input_articles"] == 1
    with TermCorpusStore(database) as store:
        assert not store.has_article("iot", "bad")
        assert store.excluded_articles("iot")[0]["exclusion_reason"] == "outside_ai_iot"


def test_policy_upgrade_refreshes_all_stored_exclusion_reasons(tmp_path):
    from app.core.term_extraction import TITLE_FILTER_POLICY

    database = tmp_path / "articles.sqlite"
    with TermCorpusStore(database) as store:
        store.record_title_exclusion("iot", "A", "AI公開と連携")
        store.connection.execute(
            "UPDATE term_title_exclusions SET policy='old',matched_terms_json='[\"公開\"]'"
        )
        store.connection.commit()
    with TermCorpusStore(database) as store:
        row = store.excluded_articles("iot")[0]
        assert row["policy"] == TITLE_FILTER_POLICY
        assert row["matched_exclusion_terms"] == ["公開", "連携"]
