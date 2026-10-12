"""Title exclusions and AI/IoT scope for keyword-count Extraction."""

import re

from app.contracts.discovery_search_vocabulary_v2 import normalized_text
from app.core.discovery_search_vocabulary import term_matches

TITLE_FILTER_POLICY = "extraction-title-keywords-v2-20261013"
TITLE_EXCLUSION_WORDS = (
    "出展",
    "締結",
    "採択",
    "日数",
    "権利化",
    "導入実績",
    "募集",
    "パートナー",
    "公開",
    "開催",
    "専門学校",
    "子会社化",
    "実証",
    "ウェビナー",
    "導入",
    "展示",
    "獲得",
    "決定",
    "突破",
    "首位",
    "維持",
    "集結",
    "登壇",
    "参画",
    "提携",
    "着手",
    "協業",
    "取得",
    "設置",
    "講演",
    "講座",
    "著書",
    "新刊",
    "公開中",
    "紹介",
    "合意",
    "試作",
    "協賛",
    "発足",
    "セミナー",
    "就任",
    "お知らせ",
    "運用",
    "開始",
    "受賞",
    "見学",
    "実習",
    "実施",
    "申請",
    "リニューアル",
    "配信",
    "運営",
    "対談",
    "提案",
    "商談",
    "選定",
    "投資",
    "月例会",
    "立ち上げ",
    "サポート",
    "社会実装",
    "連携",
    "分析",
    "拡大",
    "達成",
    "記録",
    "参入",
    "調査",
    "入会",
    "創刊",
    "本",
    "入門",
    "始動",
    "調達",
    "委託",
    "受託",
    "開設",
    "プラン集",
    "学校向け",
    "レポート",
    "イベント",
    "優勝",
    "施策",
    "ガイド",
    "公表",
    "マインドセット",
    "体験",
    "意識調査",
    "リポート",
    "完工",
    "移転",
    "ショールーム",
    "車泊",
    "ブック",
    "来場",
    "カンファレンス",
    "上演",
    "ショー",
    "マンション",
    "チーム",
    "語る",
    "施設",
    "分譲",
)


def title_exclusion_terms(title: str) -> tuple[str, ...]:
    normalized = normalized_text(title)
    return tuple(word for word in TITLE_EXCLUSION_WORDS if normalized_text(word) in normalized)


def title_is_excluded(title: str) -> bool:
    return bool(title_exclusion_terms(title))


DOMAIN_FILTER_POLICY = "extraction-ai-iot-v2-20261013"
DOMAIN_LEAD_CHARS = 1200
DOMAIN_FOOTER_PATTERN = (
    r"(?m)^[\s#\u25a0\u25c6\u25cf\u3010\uff1c\u3008\[]*"
    r"(?:会社概要|企業概要|会社紹介|企業紹介|会社情報|企業情報)"
    r"(?:[\s:\u3011\uff1e\u3009\]]|$)"
)
DOMAIN_TERMS = {
    "AI": (
        "AI",
        "人工知能",
        "機械学習",
        "ディープラーニング",
        "深層学習",
        "LLM",
        "大規模言語モデル",
        "AIoT",
        "artificial intelligence",
        "machine learning",
    ),
    "IoT": ("IoT", "Internet of Things", "モノのインターネット", "AIoT"),
}


def domain_lead(body: str) -> str:
    lead = body[:DOMAIN_LEAD_CHARS]
    footer = re.search(DOMAIN_FOOTER_PATTERN, lead)
    return lead[: footer.start()] if footer else lead


def article_domain_terms(title: str, body: str = "") -> dict[str, tuple[str, ...]]:
    """Require AI/IoT signals in the title or the main article lead, not the footer."""
    texts = (normalized_text(title), normalized_text(domain_lead(body)))
    return {
        domain: matched
        for domain, terms in DOMAIN_TERMS.items()
        if (
            matched := tuple(
                term for term in terms if any(term_matches(term, text) for text in texts)
            )
        )
    }


def article_is_in_domain(title: str, body: str = "") -> bool:
    return bool(article_domain_terms(title, body))
