"""Explainable topic classification; matches refer to exact normalized source offsets.

Change TAXONOMY to tune selection, and bump POLICY_VERSION. A topic classification
is source categorization, not proof of measured performance or product availability.
"""

import re

from app.contracts.comparison_analysis_v1 import ArticleTopicV1, TopicEvidenceV1, TopicFacetV1
from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.envelope import canonical_payload_hash
from app.core.editorial import personal_data

POLICY_VERSION = "topics-v3"
TAXONOMY = (
    ("purpose", "edge_ai", "エッジAI処理", ("エッジAI", "エッジ AI", "edge AI")),
    (
        "environment",
        "edge_device",
        "エッジ・組込み機器",
        ("エッジ環境", "エッジで", "エッジAI", "エッジ AI", "組込み", "組み込み", "edge AI"),
    ),
    (
        "function",
        "ai_inference",
        "AI推論・処理",
        ("AI推論", "AI処理", "AI演算", "推論性能", "AI inference"),
    ),
    (
        "purpose",
        "care_monitoring",
        "介護・高齢者見守り",
        ("介護", "高齢者", "安否", "elderly", "caregiving"),
    ),
    (
        "purpose",
        "industrial",
        "産業機器・設備",
        ("製造", "工場", "産業", "industrial", "manufacturing"),
    ),
    (
        "purpose",
        "education",
        "教育・学習",
        ("教材", "教育", "工作", "学習", "education", "learning"),
    ),
    ("purpose", "agriculture", "農業", ("農業", "栽培", "agriculture", "farming")),
    ("purpose", "language_model", "言語モデル", ("言語モデル", "language model", "llm")),
    (
        "environment",
        "care_facility",
        "介護施設",
        ("介護施設", "介護老人保健施設", "老人ホーム", "care facility"),
    ),
    (
        "environment",
        "private_home",
        "在宅・一般家庭",
        (
            "ひとり暮らし",
            "一人暮らし",
            "1人暮らし",
            "独居",
            "ご家庭",
            "在宅",
            "private home",
            "living alone",
        ),
    ),
    (
        "environment",
        "industrial_site",
        "産業設備",
        ("工場", "industrial installations", "industrial device", "industrial gateway"),
    ),
    (
        "environment",
        "classroom",
        "教育現場",
        ("教材", "授業", "小学校", "小中学校", "classroom", "educational"),
    ),
    (
        "function",
        "vital_fall",
        "バイタル・転倒検知",
        ("心拍", "呼吸", "転倒", "vital signs", "fall detection"),
    ),
    (
        "function",
        "activity_safety",
        "生活活動・安否確認",
        ("安否確認", "動きの有無", "活動状況", "activity monitoring"),
    ),
    ("function", "gateway", "機器接続・ゲートウェイ", ("gateway", "ゲートウェイ")),
    (
        "function",
        "learning_device",
        "学習用デバイス",
        (
            "学習用",
            "教材",
            "プログラミング工作キット",
            "プログラミング教育用ロボット",
            "educational",
            "learning device",
        ),
    ),
    ("function", "language_generation", "言語生成", ("言語モデル", "language model", "llm")),
    ("audience", "care_staff", "介護職員", ("スタッフ", "介護職員", "care staff")),
    ("audience", "family", "家族・在宅見守り者", ("ご家族", "見守る方", "family carers")),
    (
        "audience",
        "industrial_operator",
        "設備運用者",
        ("industrial installations", "工場", "industrial device"),
    ),
    (
        "article_focus",
        "trial",
        "実用性・現場検証",
        ("共同検証", "実証", "field trial", "proof of concept"),
    ),
    (
        "article_focus",
        "subsidy_registration",
        "自治体補助・登録事業者",
        ("登録事業者", "補助事業", "補助制度", "subsidy"),
    ),
    (
        "article_focus",
        "product_announcement",
        "製品発表",
        ("発表", "発売", "released", "announcement"),
    ),
)
DIMENSIONS = ("purpose", "environment", "function", "audience", "article_focus")


def keys(topic: ArticleTopicV1, dimension: str) -> set[str]:
    return {facet.key for facet in topic.facets if facet.dimension == dimension}


def classify_topic(content: NormalizedContentV1, extraction_hash: str) -> ArticleTopicV1:
    identity = canonical_payload_hash(
        {"extraction": extraction_hash, "policy": POLICY_VERSION, "taxonomy": TAXONOMY}
    )
    facets = []
    # Use editorial content only; exclude contact sections and company boilerplate.
    body = re.split(
        r"【?本件に関するお問い合わせ|会社概要|企業情報|"
        r"[^\n]{2,40}(?:株式会社|合同会社)について|Company profile",
        content.body,
        maxsplit=1,
    )[0][:6000]
    for dimension, key, label, aliases in TAXONOMY:
        evidence = []
        for field, text in (("title", content.title), ("body", body)):
            for alias in aliases:
                pattern = (
                    (r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])")
                    if alias.isascii()
                    else re.escape(alias)
                )
                match = re.search(pattern, text, flags=re.I)
                if match and not personal_data(match[0]):
                    evidence.append(
                        TopicEvidenceV1(
                            field=field, start=match.start(), end=match.end(), quote=match[0]
                        )
                    )
        if evidence:
            facets.append(
                TopicFacetV1(
                    dimension=dimension, key=key, label=label, evidence=tuple(evidence[:4])
                )
            )
    labels = []
    for dimension in ("purpose", "environment", "function", "article_focus"):
        values = [facet.label for facet in facets if facet.dimension == dimension]
        labels.append("・".join(values) if values else "未確認")
    return ArticleTopicV1(
        item_id=content.item_id,
        item_version=content.item_version,
        source_url=str(content.canonical_url),
        extraction_hash=extraction_hash,
        policy_version=POLICY_VERSION,
        input_hash=identity,
        topic_label=" / ".join(labels),
        facets=tuple(facets),
        unknown_dimensions=tuple(
            d for d in DIMENSIONS if not any(f.dimension == d for f in facets)
        ),
    )
