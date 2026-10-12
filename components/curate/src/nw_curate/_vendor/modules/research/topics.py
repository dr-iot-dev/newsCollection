"""Explainable topic classification; matches refer to exact normalized source offsets.

Change TAXONOMY to tune selection, and bump POLICY_VERSION. A topic classification
is source categorization, not proof of measured performance or product availability.
"""

import re

from nw_curate._vendor.contracts.comparison_analysis_v1 import ArticleTopicV1, TopicEvidenceV1, TopicFacetV1
from nw_curate._vendor.contracts.content_v1 import NormalizedContentV1
from nw_curate._vendor.contracts.envelope import canonical_payload_hash
from nw_curate._vendor.core.editorial import personal_data

POLICY_VERSION = "topics-v7"
TAXONOMY = (
    (
        "purpose", "public_information", "公的・公共情報の活用",
        ("公的情報", "公開情報", "公共情報", "公的データ", "公的API"),
    ),
    (
        "function", "mcp_data_access", "MCPによる外部データ接続",
        ("MCP", "Model Context Protocol"),
    ),
    (
        "environment", "application_system", "Web・アプリケーション環境",
        ("Webアプリケーション", "Webシステム", "Webサイト", "アプリケーション", "API基盤"),
    ),
    (
        "purpose", "business_automation", "業務の自動化・支援",
        (
            "業務効率", "業務自動化", "業務の自動化", "業務支援", "業務プロセス",
            "生産性", "業務オペレーション", "業務システム", "業務ツール", "業務フロー",
            "在庫管理", "カスタマーサクセス", "営業リスト", "顧客対応",
        ),
    ),
    (
        "purpose", "cyber_security", "サイバーリスク対策",
        ("サイバー", "情報セキュリティ", "脆弱性", "不正アクセス", "ランサムウェア"),
    ),
    (
        "purpose", "device_operations", "接続機器の運用・監視",
        ("IoT", "設備監視", "遠隔監視", "デバイス管理", "機器管理", "スマートメーター"),
    ),
    (
        "environment", "business_system", "企業・業務システム",
        ("企業向け", "法人向け", "企業の", "業務", "組織の", "組織向け", "社内"),
    ),
    (
        "environment", "cloud_service", "クラウド環境",
        ("クラウド", "SaaS", "cloud"),
    ),
    (
        "environment", "connected_devices", "接続機器・IoT環境",
        ("IoT", "接続機器", "センサー", "デバイス", "スマートメーター"),
    ),
    (
        "function", "generative_ai", "生成AIによる情報処理",
        ("生成AI", "生成 AI", "AIエージェント", "AI エージェント",
         "AIデータエージェント", "AI Agent", "RAG", "LLM"),
    ),
    (
        "function", "security_detection", "脅威・脆弱性の検出と対処",
        ("脆弱性", "脅威検知", "脅威を検知", "脅威の検知", "EDR", "XDR", "ランサムウェア"),
    ),
    (
        "function", "identity_access", "認証・アクセス管理",
        ("多要素認証", "アクセス管理", "アクセス制御", "認証", "ゼロトラスト"),
    ),
    (
        "function", "device_telemetry", "機器データの収集・監視",
        (
            "遠隔監視", "設備監視", "デバイス管理", "機器管理",
            "データ収集", "データの収集", "IoTプラットフォーム",
        ),
    ),

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


def classify_topic(
    content: NormalizedContentV1, extraction_hash: str,
    primary_products: tuple[str, ...] = (),
) -> ArticleTopicV1:
    identity = canonical_payload_hash(
        {"extraction": extraction_hash, "policy": POLICY_VERSION, "taxonomy": TAXONOMY,
         "primary_products": primary_products}
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
    # An explicitly announced vehicle remains a vehicle despite OTA software
    # or IoT-related corporate boilerplate. Only the title/announcement opening
    # determine this role; later customer examples cannot change the primary kind.
    vehicle_pattern = r"超小型EV|小型EV|電気自動車|電動車両|electric vehicle"
    vehicle_evidence = []
    for field, text in (("title", content.title), ("body", body[:1200])):
        match = re.search(vehicle_pattern, text, flags=re.I)
        # Body examples of customer vehicles are not the announced product.
        product_nearby = bool(
            match and any(
                re.split(r"[\uFF08(]", product, maxsplit=1)[0].casefold()
                in text[max(0, match.start() - 24):match.end() + 24].casefold()
                for product in primary_products
            )
        )
        if match and (field == "title" or product_nearby):
            vehicle_evidence.append(
                TopicEvidenceV1(
                    field=field, start=match.start(), end=match.end(), quote=match[0]
                )
            )
    if vehicle_evidence:
        facets.append(
            TopicFacetV1(
                dimension="product_kind", key="vehicle", label="車両",
                evidence=tuple(vehicle_evidence),
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
