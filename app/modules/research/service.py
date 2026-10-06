"""Conservative retrieval and relation checks over primary, verified product data."""

import re
from datetime import UTC, datetime
from typing import Literal

from app.contracts.comparison_analysis_v1 import ArticleTopicV1, SelectionCheckV1
from app.contracts.evidence_v1 import EvidencePackageV1

POLICY_VERSION = "research-v3"
APPLICATIONS = (
    ("介護", "見守り", "高齢者", "安否", "elderly", "caregiving"),
    ("製造", "工場", "産業", "設備", "industrial", "manufacturing"),
    ("教材", "教育", "工作", "講座", "学習", "education", "learning"),
    ("農業", "農薬", "栽培", "agriculture", "farming"),
)
PRODUCT_CLASSES = (
    ("gateway", "ゲートウェイ"),
    ("sensor", "センサー", "センサ"),
    ("camera", "カメラ"),
    ("microcontroller", "マイコン", "mcu"),
    ("llm", "language model", "言語モデル"),
    ("database", "データベース"),
    ("robot", "ロボット"),
    ("smart home", "home automation", "スマートホーム"),
    ("operating system", "オペレーティングシステム"),
    ("ai accelerator", "gpu", "npu", "アクセラレータ"),
)
STOP_WORDS = frozenset(
    """the and for with from this that company product companyname release
released announcement announced manufacturer supported integration provides primary information
specification features describes documented official news new update version software hardware
support price launch available availability technology platform cloud solution solutions systems
system using designed performance security introduces introduction details information about
its has have are was were will can not only today more also our their
into each than through""".split()
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def terms(text: str) -> set[str]:
    return {
        re.sub(r"[0-9]+", "", word.casefold()).strip("-_")
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
        if re.sub(r"[0-9]+", "", word.casefold()).strip("-_") not in STOP_WORDS
        and len(re.sub(r"[0-9]+", "", word)) >= 3
    }


def classes(text: str) -> set[int]:
    text = text.casefold()
    return {
        index
        for index, aliases in enumerate(PRODUCT_CLASSES)
        if any(
            (
                re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", text)
                if alias.isascii()
                else alias in text
            )
            for alias in aliases
        )
    }


def identity(package: EvidencePackageV1, kind: str) -> str | None:
    values = {fact.value.casefold() for fact in package.verified_facts if fact.fact_type == kind}
    return next(iter(values)) if len(values) == 1 else None


def relevance_score(target: EvidencePackageV1, target_body: str, title: str, body: str) -> int:
    """Legacy keyword diagnostic; eligibility and ranking use topic/feature audits."""
    company = terms(identity(target, "organization") or "")
    target_text = target.title + " " + (identity(target, "product") or "")
    target_terms = terms(target_text) - company
    other_terms = terms(title + " " + body[:5000]) - company
    overlap = target_terms & other_terms
    target_use = {
        index
        for index, aliases in enumerate(APPLICATIONS)
        if any(alias in (target_text + " " + target_body[:1200]).casefold() for alias in aliases)
    }
    other_use = {
        index
        for index, aliases in enumerate(APPLICATIONS)
        if any(alias in (title + " " + body[:1200]).casefold() for alias in aliases)
    }
    if target_use and other_use and not target_use & other_use:
        return 0
    class_overlap = classes(target_text + " " + target_body[:5000]) & classes(
        title + " " + body[:5000]
    )
    product_family = terms(identity(target, "product") or "") - company
    if class_overlap:
        return 10 * len(class_overlap) + 10 * len(target_use & other_use) + len(overlap)
    if product_family & other_terms:
        return 5 + len(overlap)
    return len(overlap) if len(overlap) >= 2 else 0


def relation_reason(
    target: EvidencePackageV1,
    candidate: EvidencePackageV1,
    relation: Literal["previous", "competitor"],
    relevance: int,
) -> str | None:
    company = identity(target, "organization")
    other_company = identity(candidate, "organization")
    if not company or not other_company or not identity(candidate, "product"):
        return "PRODUCT_IDENTITY_UNCONFIRMED"
    if relation == "previous":
        if company != other_company:
            return "PREVIOUS_PRODUCT_COMPANY_MISMATCH"
        if (
            not target.published_at
            or not candidate.published_at
            or utc(candidate.published_at) >= utc(target.published_at)
        ):
            return "PREVIOUS_PRODUCT_DATE_UNCONFIRMED"
    elif company == other_company:
        return "COMPETITOR_COMPANY_MISMATCH"
    if relevance <= 0:
        return "PRODUCT_RELEVANCE_UNCONFIRMED"
    return None


def topic_checks(target: ArticleTopicV1, candidate: ArticleTopicV1) -> tuple[SelectionCheckV1, ...]:
    from app.modules.research.topics import keys

    checks = []
    for dimension in ("purpose", "environment", "function", "audience", "article_focus"):
        left, right = keys(target, dimension), keys(candidate, dimension)
        result = "unknown" if not left or not right else "pass" if left & right else "fail"
        explanation = (
            "分類根拠が不足している。"
            if result == "unknown"
            else "この観点のトピックが共通する。"
            if result == "pass"
            else "この観点のトピックが異なる。"
        )
        if dimension == "article_focus":
            explanation += "発表・検証・補助登録などの主題差は記録するが、単独の除外条件にしない。"
        checks.append(
            SelectionCheckV1(
                criterion=dimension,
                required=dimension in {"purpose", "environment", "function"},
                result=result,
                target_values=tuple(sorted(left)),
                candidate_values=tuple(sorted(right)),
                explanation=explanation,
            )
        )
    return tuple(checks)


def topic_reasons(checks: tuple[SelectionCheckV1, ...]) -> tuple[str, ...]:
    return tuple(
        "TOPIC_"
        + check.criterion.upper()
        + ("_UNCONFIRMED" if check.result == "unknown" else "_MISMATCH")
        for check in checks
        if check.criterion in {"purpose", "environment", "function"} and check.result != "pass"
    )
