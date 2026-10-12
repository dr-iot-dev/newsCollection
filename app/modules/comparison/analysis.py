"""Compare semantic feature axes, retaining fact references and unknown conditions."""

import re

from app.contracts.comparison_analysis_v1 import FeatureComparisonV1, FeatureSideV1
from app.contracts.facts_v1 import VerifiedFactV1

FEATURES = (
    (
        "security_diagnostic_scope", "診断するシステム・情報",
        ("Web", "ネットワーク", "API", "ソースコード", "認証", "脆弱性"),
    ),

    ("ai_retrieval", "情報検索・参照", ("RAG", "検索", "ナレッジ", "文書", "情報源", "知識")),
    (
        "ai_output", "生成・分析する内容",
        ("文章", "資料", "レポート", "要約", "分析", "コード", "返信文"),
    ),
    (
        "ai_operation", "AI処理の実行方法",
        ("AIエージェント", "AI エージェント", "自動化", "ワークフロー", "チャット", "AIが一次受付"),
    ),
    ("deployment", "実行・提供環境", ("クラウド", "SaaS", "オンプレミス", "エッジ")),
    (
        "security_controls", "防御・アクセス制御",
        ("脆弱性", "ランサムウェア", "EDR", "XDR", "多要素認証", "アクセス制御", "ゼロトラスト"),
    ),
    (
        "device_management", "機器データと運用",
        (
            "データ収集", "データの収集", "データを収集", "データ解析", "可視化",
            "遠隔監視", "遠隔制御", "デバイス管理", "機器管理",
            "設備監視", "MQTT", "HTTP", "API",
            "現場作業データ", "現場での記録", "点検情報", "IoTデータ", "回線モニタリング",
            "センサーデータ", "設備データ", "自動制御",
        ),
    ),

    (
        "ai_processor",
        "AI処理チップ",
        ("Jetson AGX Orin", "Jetson Orin NX", "Jetson Orin Nano", "RZ/V2H", "Hailo-8L"),
    ),
    (
        "sensing_method",
        "検知方式",
        (
            "ミリ波",
            "人感センサー",
            "レーダー",
            "体動を検知するセンサー",
            "millimeter wave",
            "motion sensor",
        ),
    ),
    ("observed_signals", "観測する状態", ("心拍", "呼吸", "転倒", "在室", "動きの有無")),
    ("communication", "通信方式", ("LoRaWAN", "LTE", "Wi-Fi", "Bluetooth", "Ethernet", "SIM")),
    (
        "programming_method",
        "プログラミング方法",
        ("ビジュアルプログラミング", "ビジュアル・プログラミング"),
    ),
    ("notification", "通知手段", ("LINE", "メール", "スマートフォン", "email")),
    (
        "camera_policy",
        "カメラの使用",
        ("カメラを使わず", "カメラ不要", "カメラ不使用", "カメラなし"),
    ),
)
GENERIC_AXES = (
    ("memory", "メモリー容量", "hardware_spec"),
    ("compatibility", "互換性", "compatibility"),
    ("software", "ソフトウェア要件", "software_requirement"),
    ("price", "価格と適用条件", "price"),
    ("standard", "標準", "standard"),
    ("license", "ライセンス", "license"),
)


def side(facts: tuple[VerifiedFactV1, ...], axis: str) -> FeatureSideV1:
    values: set[str] = set()
    matched = []
    aliases = next((aliases for key, _, aliases in FEATURES if key == axis), ())
    generic = next((kind for key, _, kind in GENERIC_AXES if key == axis), None)
    for fact in facts:
        if fact.fact_type in {"organization", "product", "release_date", "availability_region"}:
            continue
        found = []
        for alias in aliases:
            # Capability values only: no mere attribution, subject or eligibility metadata.
            pattern = re.escape(alias)
            if alias.isascii():
                pattern = r"(?<![A-Za-z])" + pattern + r"(?![A-Za-z])"
            if re.search(pattern, fact.value, re.I):
                found.append(
                    "カメラ不使用"
                    if axis == "camera_policy"
                    else "ビジュアルプログラミング"
                    if axis == "programming_method"
                    else alias
                )
        if axis == "memory" and fact.fact_type == generic:
            found = [m[0] for m in re.finditer(r"[0-9]+(?:\.[0-9]+)?\s*(?:GB|MB)", fact.value)]
        elif generic and axis != "memory" and fact.fact_type == generic:
            # Requirement labels containing only a radio protocol are not a shared software axis.
            if axis != "software" or not any(
                a.casefold() in fact.value.casefold() for a in ("LoRaWAN", "LTE", "LINE")
            ):
                found = [fact.value]
        if axis == "compatibility" and not re.search(
            r"互換|対応|連携|compatible|integration|supports?", fact.value, re.I
        ):
            found = []
        if found:
            values.update(found)
            matched.append(fact)
    conditions = tuple(
        sorted(
            {
                str(value)
                for fact in matched
                for value in (fact.conditions, fact.region, fact.unit, fact.currency)
                if value
            }
        )
    )
    if axis == "price" and any(not f.conditions or not f.region for f in matched):
        conditions += ("価格の地域・適用条件は未確認",)
    return FeatureSideV1(
        values=tuple(sorted(values)),
        fact_ids=tuple(f.fact_id for f in matched),
        evidence_ids=tuple(f.evidence_id for f in matched),
        conditions=conditions,
    )


def compare_features(
    target: tuple[VerifiedFactV1, ...], candidate: tuple[VerifiedFactV1, ...]
) -> tuple[FeatureComparisonV1, ...]:
    result = []
    for axis, label in [(key, label) for key, label, _ in (*FEATURES, *GENERIC_AXES)]:
        left, right = side(target, axis), side(candidate, axis)
        if not left.values or not right.values:
            outcome, explanation = (
                "unknown",
                "この比較軸として抽出できた検証済み特徴が片側または両側にない。原文の未記載・欠如・非対応を意味しない。",
            )
        elif axis == "price" and (
            left.conditions != right.conditions
            or any("未確認" in c for c in (*left.conditions, *right.conditions))
        ):
            outcome, explanation = (
                "not_comparable",
                "地域・補助・料金条件を揃えられないため、価格の優劣を比較しない。",
            )
        elif set(left.values) == set(right.values):
            outcome, explanation = (
                "common",
                "この観点の確認済み記載が一致する。性能の同等性は意味しない。",
            )
        elif set(left.values) & set(right.values):
            outcome, explanation = (
                "partial_overlap",
                "確認済み記載に共通部分と異なる部分がある。未記載部分は非対応と扱わない。",
            )
        else:
            outcome, explanation = (
                "different",
                "この観点の確認済み記載が異なる。条件を揃えた性能・優劣の評価ではない。",
            )
        result.append(
            FeatureComparisonV1(
                axis=axis,
                label=label,
                target=left,
                candidate=right,
                result=outcome,
                explanation=explanation,
            )
        )
    return tuple(result)
