"""Publisher type gates both legacy and new articles before any keyword search."""

from app.contracts.discovery_search_vocabulary_v2 import DiscoveryArticle
from app.infrastructure.prtimes_release_type import public_release_type
from app.infrastructure.term_corpus import TermCorpusStore
from tests.unit.test_discovery_search_vocabulary import vocabulary


def test_official_type_is_not_inferred_from_article_prose() -> None:
    assert public_release_type("<p>これは商品サービスです</p>") is None
    assert public_release_type(
        '<div id="press-release-body"><a href="/main/html/searchrlp/release_type_id/01/">'
        "商品サービス</a></div><dl><dt>種類</dt><dd>"
        '<a href="/main/html/searchrlp/release_type_id/02/">経営情報</a></dd></dl>'
    ) == ("02", "経営情報")
    assert public_release_type(
        '<dl><dt>種類</dt><dd><a href="/main/html/searchrlp/release_type_id/01/">'
        "商品サービス</a></dd></dl>"
    ) == ("01", "商品サービス")


def test_existing_nonproduct_and_unknown_never_reach_matching(tmp_path) -> None:
    database = tmp_path / "articles.sqlite"
    with TermCorpusStore(database) as store:
        store.create_corpus("iot", "IoT")
        for ident in ("product", "event", "unknown"):
            store.import_article(
                "iot", DiscoveryArticle(article_id=ident, title="IoTサービス", body="価格 " + ident)
            )
        key = store.save_vocabulary(vocabulary())
        store.require_product_service("iot")
        assert store.article_count("iot") == 0
        store.record_release_type(
            "iot", "product", "IoTサービス", "", ("01", "商品サービス"), "hash"
        )
        store.record_release_type("iot", "event", "IoTサービス", "", ("03", "イベント"), "hash")
        seen = []
        store.connection.create_function(
            "phrase_match", 2, lambda word, text: seen.append(text) or word in text
        )
        assert [r["article_id"] for r in store.count_candidates("iot", key)] == ["product"]
        assert [a.article_id for a in store.articles("iot")] == ["product"]
        assert store.article_count("iot") == 1
        assert all("event" not in text and "unknown" not in text for text in seen)
    with TermCorpusStore(database) as store:
        assert store.article_count("iot") == 1
        assert store.stored_article_count("iot") == 3


def test_new_article_requires_confirmed_product_kind(tmp_path) -> None:
    with TermCorpusStore(tmp_path / "articles.sqlite") as store:
        store.create_corpus("iot", "IoT")
        store.require_product_service("iot")
        article = DiscoveryArticle(article_id="new", title="AI新サービス", body="IoT価格")
        assert not store.import_article("iot", article)
        store.record_release_type("iot", "new", article.title, "", ("01", "商品サービス"), "hash")
        assert store.import_article("iot", article)
        store.record_release_type("iot", "new", article.title, "", ("02", "経営情報"), "hash")
        assert store.article_count("iot") == 0
        assert store.excluded_articles("iot")[0]["exclusion_reason"] == "outside_product_service"


def test_new_words_reclassify_legacy_articles(tmp_path) -> None:
    with TermCorpusStore(tmp_path / "articles.sqlite") as store:
        store.create_corpus("iot", "IoT")
        store.import_article(
            "iot", DiscoveryArticle(article_id="old", title="AI新製品", body="価格")
        )
        store.connection.execute(
            "UPDATE term_articles SET title=?,title_filter_policy=? WHERE article_id='old'",
            ("AI機能を強化", "extraction-title-keywords-v2-20261013"),
        )
        store.connection.commit()
    with TermCorpusStore(tmp_path / "articles.sqlite") as store:
        assert store.article_count("iot") == 0
        excluded = store.excluded_articles("iot")[0]
        assert excluded["matched_exclusion_terms"] == ["強化"]
