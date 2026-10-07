"""Deterministic, source-numbered comparisons from verified article-package facts."""

import re

from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.facts_v1 import VerifiedFactV1
from app.core.draft_style import plain_style

UNKNOWN = "資料で確認できず"
TABLE_ROWS = (
    ("organization", "提供元"),
    ("version", "バージョン"),
    ("hardware_spec", "技術・機能仕様"),
    ("software_requirement", "ソフトウェア・通信要件"),
    ("compatibility", "対応・連携"),
    ("price", "価格と適用条件"),
    ("release_date", "発売・提供開始時期"),
    ("availability_region", "提供地域"),
    ("standard", "標準"),
    ("license", "ライセンス"),
    ("support_end_date", "サポート終了時期"),
    ("performance_claim", "提供元による性能の説明"),
    ("security_claim", "提供元による安全性の説明"),
)


def source_urls(package: ArticlePackageV1) -> tuple[str, ...]:
    """Keep first-reference order and use one number per distinct URL."""
    return tuple(dict.fromkeys(str(ref.url) for ref in package.source_references if ref.url))


def render_source_list(package: ArticlePackageV1) -> str:
    return "\n".join(f"- 資料{i}: {url}" for i, url in enumerate(source_urls(package), 1))


def table_cell(value: str) -> str:
    # Escape Markdown syntax without allowing values to add links, cells or HTML.
    value = " ".join(value.split())
    return re.sub(r"([\\`*_{\[\]}<>!|])", r"\\\1", value)


def fact_text(fact: VerifiedFactV1) -> str:
    parts = [fact.value]
    for extra in (fact.unit, fact.currency, fact.region, fact.conditions):
        if extra and extra not in fact.value and extra not in parts:
            parts.append(extra)
    value = parts[0] + ("\uff08" + "、".join(parts[1:]) + "\uff09" if len(parts) > 1 else "")
    if fact.attribution:
        value = fact.attribution + "によると、" + value
    return table_cell(plain_style(value))


def render_comparison_table(package: ArticlePackageV1) -> str:
    allowed = set(package.verified_fact_ids)
    columns: list[tuple[int, str, tuple[VerifiedFactV1, ...]]] = []
    for number, url in enumerate(source_urls(package), 1):
        fact_ids = {
            fact_id
            for ref in package.source_references
            if ref.url and str(ref.url) == url
            for fact_id in ref.fact_ids
        } & allowed
        facts = tuple(f for f in package.facts if f.fact_id in fact_ids)
        if any(f.fact_type == "product" for f in facts):
            columns.append((number, url, facts))
    if len(columns) < 2:
        return ""
    headers = ["比較項目"]
    for number, url, facts in columns:
        names = dict.fromkeys(f.value for f in facts if f.fact_type == "product")
        headers.append(table_cell(" / ".join(names)) + f" [資料{number}]({url})")
    rows = []
    for kind, label in TABLE_ROWS:
        if not any(f.fact_type == kind for _, _, facts in columns for f in facts):
            continue
        cells = []
        for _, _, facts in columns:
            values = dict.fromkeys(fact_text(f) for f in facts if f.fact_type == kind)
            cells.append(" / ".join(values) if values else UNKNOWN)
        rows.append("| " + " | ".join([label, *cells]) + " |")
    if not rows:
        return ""
    return (
        "\n\n## 比較表\n\n各提供元の発表資料に記載された内容を整理した。\n\n"
        + "| "
        + " | ".join(headers)
        + " |\n"
        + "| "
        + " | ".join("---" for _ in headers)
        + " |\n"
        + "\n".join(rows)
        + "\n\n「資料で確認できず」は非対応を意味しない。"
        + "記載された条件での比較であり、性能や価格の優劣を示すものではない。"
    )


def comparison_prose(body: str, package: ArticlePackageV1) -> tuple[bool, str]:
    """Remove only the exact verified table; changed or extra tables remain untrusted."""
    table = render_comparison_table(package)
    valid = body.count(table) == 1 if table else "## 比較表" not in body
    prose = body.replace(table, "", 1) if table and valid else body
    return valid and "## 比較表" not in prose, prose
