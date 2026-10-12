import hashlib
from uuid import uuid4

from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.facts_v1 import VerifiedFactV1
from app.modules.comparison.analysis import compare_features
from app.modules.research.service import topic_checks, topic_reasons
from app.modules.research.topics import classify_topic


def content(body):
    return NormalizedContentV1(
        item_id=uuid4(), item_version=1, snapshot_id=uuid4(),
        canonical_url="https://example.test/article", title="製品発表", body=body,
        body_sha256=hashlib.sha256(body.encode()).hexdigest(), date_precision="unknown",
        language="ja", language_confidence=1, language_source="fixture",
        extraction_method="fixture", quality_score=1, quality_reasons=(),
    )


def topic(body):
    return classify_topic(content(body), "sha256:" + "0" * 64)


def test_requested_categories_require_supported_purpose_environment_and_function():
    groups = (
        (
            "企業向け生成AIで業務効率を改善するクラウドサービス。",
            "業務自動化のためのSaaS型AIエージェント。",
        ),
        ("IoTプラットフォームによる遠隔監視とデータ収集。", "IoT機器の設備監視とデバイス管理。"),
        ("企業向けサイバー対策で脆弱性を検出する。", "社内の情報セキュリティ対策としてEDRを提供。"),
    )
    for left, right in groups:
        assert not topic_reasons(topic_checks(topic(left), topic(right)))
        for body in (left, right):
            classified = topic(body)
            for facet in classified.facets:
                for evidence in facet.evidence:
                    value = "製品発表" if evidence.field == "title" else body
                    assert value[evidence.start:evidence.end] == evidence.quote


def test_security_identity_and_detection_are_not_assumed_the_same_function():
    left = topic("企業向け情報セキュリティ対策の多要素認証。")
    right = topic("企業向け情報セキュリティ対策の脆弱性検出。")
    assert "TOPIC_FUNCTION_MISMATCH" in topic_reasons(topic_checks(left, right))
    assert "TOPIC_FUNCTION_UNCONFIRMED" in topic_reasons(
        topic_checks(topic("企業向けクラウドサービス。"), topic("企業向けクラウドサービス。"))
    )


def fact(value):
    return VerifiedFactV1(fact_id=uuid4(), evidence_id=uuid4(), fact_type="hardware_spec",
                          subject="発表内容", predicate="機能", value=value)


def test_new_feature_axes_keep_fact_evidence_and_missing_values_unknown():
    a = fact("RAG検索と文章の要約をクラウドで提供")
    b = fact("RAG検索とレポート分析をオンプレミスで提供")
    rows = {r.axis: r for r in compare_features((a,), (b,))}
    assert rows["ai_retrieval"].result == "common"
    assert rows["ai_output"].result == "different"
    assert rows["deployment"].result == "different"
    assert rows["ai_retrieval"].target.fact_ids == (a.fact_id,)
    assert rows["security_controls"].result == "unknown"


def test_public_information_mcp_connections_share_supported_topics():
    groups = (
        "業務で公開情報をAIチャットから参照するMCP接続サービス。",
        "社内の提案に公共情報を使うMCP機能。",
        "公的APIをMCPサーバーとして提供し、企業の導入判断を支援する。",
    )
    for body in groups[1:]:
        assert not topic_reasons(topic_checks(topic(groups[0]), topic(body)))
    unrelated = topic("社内の業務支援でMCP接続を提供する。")
    assert "TOPIC_PURPOSE_MISMATCH" in topic_reasons(
        topic_checks(topic("公開情報をMCPから参照するアプリケーション。"), unrelated)
    )


def test_web_diagnosis_environment_requires_source_evidence():
    a = topic("脆弱性をソースコードから解析してWebシステムを診断する。")
    b = topic("Webアプリケーションの脆弱性を検出する。")
    assert not topic_reasons(topic_checks(a, b))
    assert "TOPIC_ENVIRONMENT_UNCONFIRMED" in topic_reasons(
        topic_checks(a, topic("脆弱性を診断する。"))
    )


def test_device_data_and_automatic_control_keep_evidence_references():
    a = fact("現場のセンサーデータと設備データを取得する")
    b = fact("クラウドから換気設備の風量を自動制御する")
    row = next(r for r in compare_features((a,), (b,)) if r.axis == "device_management")
    assert row.target.fact_ids == (a.fact_id,)
    assert row.candidate.fact_ids == (b.fact_id,)
    assert row.result == "different"
