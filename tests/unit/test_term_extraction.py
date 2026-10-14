"""Exactly the user-specified title words; no semantic exceptions or body filtering."""

import pytest

from app.core.term_extraction import (
    DOMAIN_LEAD_CHARS,
    TITLE_EXCLUSION_WORDS,
    article_domain_terms,
    article_is_in_domain,
    title_exclusion_terms,
)


@pytest.mark.parametrize("word", TITLE_EXCLUSION_WORDS)
def test_each_requested_word_excludes_a_matching_title(word):
    assert word in title_exclusion_terms(f"製品についての{word}ニュース")


def test_multiple_matches_and_duplicate_user_terms():
    assert len(TITLE_EXCLUSION_WORDS) == len(set(TITLE_EXCLUSION_WORDS)) == 111
    assert title_exclusion_terms("パートナー提携でセミナー開催を開始") == (
        "パートナー",
        "開催",
        "提携",
        "セミナー",
        "開始",
    )
    assert title_exclusion_terms("公開中のお知らせ") == ("公開", "公開中", "お知らせ")


def test_product_or_negative_phrasing_does_not_override_literal_title_rule():
    assert title_exclusion_terms("新製品の提供開始") == ("開始",)
    assert title_exclusion_terms("導入不要のセンサー") == ("導入",)
    assert title_exclusion_terms("新機種の価格と仕様") == ()
    assert title_exclusion_terms("開 始について") == ()


def test_new_words_are_literal_and_duplicate_admission_is_removed():
    assert TITLE_EXCLUSION_WORDS.count("入会") == 1
    assert title_exclusion_terms("日本初のAI製品") == ("本",)
    assert title_exclusion_terms("AI連携の分析") == ("連携", "分析")


@pytest.mark.parametrize(
    "title,domain",
    [
        ("AI機能", "AI"),
        ("人工知能製品", "AI"),
        ("機械学習モデル", "AI"),
        ("LLM機能", "AI"),
        ("大規模言語モデル", "AI"),
        ("ＡＩ機能", "AI"),
        ("IoT端末", "IoT"),
        ("Internet of Things device", "IoT"),
    ],
)
def test_domains_accept_explicit_topic_terms(title, domain):
    assert domain in article_domain_terms(title)


def test_domains_require_title_or_lead_signal_not_footer_or_english_substring():
    assert article_is_in_domain("新商品", "IoTセンサーの製品です。")
    assert set(article_domain_terms("AIoT端末")) == {"AI", "IoT"}
    assert not article_is_in_domain("一般商品", "一般ニュースです。")
    assert not article_is_in_domain("ThailandのIoTivity製品")
    assert not article_is_in_domain("新商品", "あ" * DOMAIN_LEAD_CHARS + "会社概要:AI事業")


@pytest.mark.parametrize("heading", ["会社概要", "【企業概要】", "■会社情報", "会社紹介:"])
def test_company_footer_within_first_1200_chars_does_not_establish_topic(heading):
    assert not article_is_in_domain(
        "一般商品", f"一般商品の説明です。\n\n{heading}\nAI事業を展開する企業です。"
    )
    assert article_is_in_domain("AI製品", f"製品の説明です。\n{heading}\n企業の情報")
