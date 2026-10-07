import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.auth import create_user
from app.contracts.content_v1 import NormalizedContentV1
from app.contracts.envelope import canonical_payload_hash
from app.contracts.facts_v1 import VerifiedFactV1
from app.core.editorial import EditorialError
from app.infrastructure.db.models import AiRun, ExtractionResult, ModuleMessage
from app.infrastructure.db.session import get_db
from app.main import create_app
from app.modules.comparison.analysis import compare_features
from app.modules.research.service import topic_checks, topic_reasons
from app.modules.research.topics import classify_topic
from app.orchestration.comparison_analysis import analysis_for_items, record_contract
from app.orchestration.editorial import checked_payload
from tests.unit.test_comparison_research import prepared_root, seed_articles


def content(title, body):
    return NormalizedContentV1(
        item_id=uuid4(),
        item_version=1,
        snapshot_id=uuid4(),
        canonical_url="https://example.test/article",
        title=title,
        body=body,
        body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        date_precision="unknown",
        language="ja",
        language_confidence=1,
        language_source="fixture",
        extraction_method="fixture",
        quality_score=1,
        quality_reasons=(),
    )


def fact(value, kind="hardware_spec", **kwargs):
    return VerifiedFactV1(
        fact_id=uuid4(),
        evidence_id=uuid4(),
        fact_type=kind,
        subject="発表内容",
        predicate="documented capability",
        value=value,
        **kwargs,
    )


def test_topics_distinguish_facility_vitals_trial_from_home_activity_subsidy():
    facility = content(
        "介護支援システムの共同検証",
        "介護老人保健施設で、スタッフ向けに心拍・呼吸・転倒を検知する。",
    )
    home = content(
        "高齢者見守りの登録事業者",
        "ひとり暮らしの方に補助事業を案内。ご家族が動きの有無・活動状況を確認する。",
    )
    left, right = (classify_topic(v, "sha256:" + "0" * 64) for v in (facility, home))
    checks = topic_checks(left, right)
    assert next(c for c in checks if c.criterion == "purpose").result == "pass"
    assert "TOPIC_ENVIRONMENT_MISMATCH" in topic_reasons(checks)
    assert "TOPIC_FUNCTION_MISMATCH" in topic_reasons(checks)
    assert "実用性・現場検証" in left.topic_label
    assert "自治体補助・登録事業者" in right.topic_label
    for source, topic in ((facility, left), (home, right)):
        for facet in topic.facets:
            for evidence in facet.evidence:
                assert (
                    getattr(source, evidence.field)[evidence.start : evidence.end] == evidence.quote
                )


def test_same_topic_can_compare_different_announcement_events_but_records_the_difference():
    left = classify_topic(
        content("介護施設の共同検証", "スタッフ向けに心拍・転倒を検知する。"), "left"
    )
    right = classify_topic(
        content("介護施設向け製品を発表", "スタッフ向けに心拍・転倒を検知する。"), "right"
    )
    checks = topic_checks(left, right)
    assert not topic_reasons(checks)
    assert all(c.required for c in checks if c.criterion in {"purpose", "environment", "function"})
    assert not next(c for c in checks if c.criterion == "article_focus").required
    assert next(c for c in checks if c.criterion == "article_focus").result == "fail"


def test_unknown_function_is_not_filled_in_from_generic_sensor_matching():
    left = classify_topic(content("介護施設の見守り", "スタッフが使うsensor。"), "left")
    right = classify_topic(content("介護施設の見守り", "スタッフが使うcamera。"), "right")
    assert "TOPIC_FUNCTION_UNCONFIRMED" in topic_reasons(topic_checks(left, right))


def test_feature_comparison_has_evidence_and_preserves_missing_and_price_conditions():
    left = (
        fact("カメラを使わず心拍・呼吸・転倒を検知する"),
        fact("LoRaWAN", "software_requirement"),
        fact("月額89円", "price", currency="JPY", unit="円"),
    )
    right = (
        fact("心拍・呼吸・在室を検知する"),
        fact("LTE", "hardware_spec"),
        fact("LINEで通知する", "software_requirement"),
        fact(
            "月額89円", "price", currency="JPY", unit="円", region="千葉市", conditions="補助適用後"
        ),
    )
    rows = {r.axis: r for r in compare_features(left, right)}
    assert rows["observed_signals"].result == "partial_overlap"
    assert rows["communication"].result == "different"
    assert rows["notification"].result == "unknown"
    assert rows["camera_policy"].result == "unknown"
    assert rows["price"].result == "not_comparable"
    assert rows["communication"].target.evidence_ids == (left[1].evidence_id,)
    assert rows["communication"].candidate.fact_ids == (right[1].fact_id,)
    common = {r.axis: r for r in compare_features((fact("LTE"),), (fact("LTE"),))}
    assert common["communication"].result == "common"


def replace_content(session, item, title, body):
    row = session.scalar(
        select(ExtractionResult).where(
            ExtractionResult.item_id == item.id, ExtractionResult.revision == item.version
        )
    )
    dto = checked_payload(row, NormalizedContentV1)
    dto = dto.model_copy(
        update={
            "title": title,
            "body": body,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
    )
    row.payload_json = dto.model_dump(mode="json")
    row.payload_hash = canonical_payload_hash(row.payload_json)
    session.flush()


def test_mismatched_topic_is_recorded_and_rejected_even_for_manual_references(acquisition_session):
    session = acquisition_session
    target, _, candidate = seed_articles(session)
    replace_content(
        session,
        target,
        "介護施設の共同検証",
        (
            "Company: ExampleCorp\nProduct: ABC100\n仕様: 8GB\n価格: 19,800円\n"
            "介護老人保健施設でスタッフが心拍・呼吸・転倒を検知する。"
        ),
    )
    replace_content(
        session,
        candidate,
        "高齢者見守りの登録事業者",
        (
            "Company: OtherCorp\nProduct: XYZ200\n仕様: 16GB\n価格: 29,800円\n"
            "ひとり暮らしの方が対象の補助事業。ご家族が活動状況や動きの有無を確認する。"
        ),
    )
    service = prepared_root(session, target)
    service.facts(candidate.id)
    analysis = analysis_for_items(service, target, competitor_ids=(candidate.id,))
    pair = analysis.candidates[0]
    assert pair.decision == "rejected"
    assert "TOPIC_ENVIRONMENT_MISMATCH" in pair.reason_codes
    assert pair.features and pair.shared_feature_axes  # specs alone cannot override topic
    session.commit()
    stored = session.scalar(
        select(ModuleMessage).where(ModuleMessage.consumer == "comparison_audit")
    )
    assert stored.payload_json == analysis.model_dump(mode="json")
    with pytest.raises(EditorialError, match="TOPIC_ENVIRONMENT_MISMATCH"):
        service.comparison(target.id, competitor_ids=(candidate.id,))


def test_topics_and_analysis_are_append_only_idempotent_and_exposed_without_ai(acquisition_session):
    session = acquisition_session
    target, _, candidate = seed_articles(session)
    service = prepared_root(session, target)
    service.facts(candidate.id)
    session.commit()
    _actor, token = create_user(session, "analyst", ["editor"])
    _, viewer_token = create_user(session, "reader", ["viewer"])
    session.commit()
    version = target.workflow_version
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        url = f"/api/v1/items/{target.id}/comparison-analysis"
        payload = {"expected_version": version, "competitor_item_ids": [str(candidate.id)]}
        assert (
            client.post(
                url, json=payload, headers={"Authorization": "Bearer " + viewer_token}
            ).status_code
            == 403
        )
        headers = {"Authorization": "Bearer " + token}
        first = client.post(url, json=payload, headers=headers)
        assert first.status_code == 200
        second = client.post(url, json=payload, headers=headers)
        assert second.json()["analysis_id"] == first.json()["analysis_id"]
        assert first.json()["analysis"]["candidates"][0]["decision"] == "eligible"
        detail = client.get(f"/api/v1/items/{target.id}", headers=headers).json()
        assert detail["topic_profile"]["topic_label"]
        assert detail["comparison_analyses"]
        history = client.get(url, headers=headers).json()
        assert len(history["analyses"]) == 1
    assert not session.scalars(select(AiRun)).all()
    assert target.workflow_version == version
    first_analysis = analysis_for_items(service, target, competitor_ids=(candidate.id,))
    first_key = record_contract(service, first_analysis, "comparison_audit")
    replace_content(session, candidate, "新しい介護施設の発表", "介護施設で心拍を検知します。")
    next_analysis = analysis_for_items(service, target, competitor_ids=(candidate.id,))
    next_key = record_contract(service, next_analysis, "comparison_audit")
    assert first_key != next_key
    assert session.get(ModuleMessage, first_key).payload_json == first_analysis.model_dump(
        mode="json"
    )


def test_concrete_protocol_axis_does_not_require_matching_generic_fact_kinds(acquisition_session):
    from app.contracts.evidence_v1 import EvidencePackageV1
    from app.modules.research.service import relation_reason

    target = EvidencePackageV1(
        item_id=uuid4(),
        canonical_url="https://example.test/one",
        title="gateway",
        language="en",
        facts=(),
        quality_score=1,
        verified_facts=(
            fact("CompanyA", "organization"),
            fact("GatewayA", "product"),
            fact("LoRaWAN", "software_requirement"),
        ),
    )
    other = EvidencePackageV1(
        item_id=uuid4(),
        canonical_url="https://example.test/two",
        title="gateway",
        language="en",
        facts=(),
        quality_score=1,
        verified_facts=(
            fact("CompanyB", "organization"),
            fact("GatewayB", "product"),
            fact("LTE", "hardware_spec"),
        ),
    )
    assert relation_reason(target, other, "competitor", 300) is None
    assert (
        next(
            row
            for row in compare_features(target.verified_facts, other.verified_facts)
            if row.axis == "communication"
        ).result
        == "different"
    )


def test_a_misclassified_camera_claim_is_not_a_compatibility_feature():
    value = fact("カメラ不要・非接触によるストレスフリーな見守り", "compatibility")
    row = next(r for r in compare_features((value,), (value,)) if r.axis == "compatibility")
    assert row.result == "unknown" and not row.target.values


def test_robot_learning_topic_excludes_other_products_in_company_boilerplate():
    left = classify_topic(
        content(
            "プログラミング工作キット",
            "小中学校でロボットづくり。\nユカイ工学株式会社について\n呼吸するクッションを提供。",
        ),
        "left",
    )
    right = classify_topic(
        content("プログラミング教育用ロボット", "小学校のプログラミング教育を支援。"), "right"
    )
    assert not topic_reasons(topic_checks(left, right))
    assert all(f.key != "vital_fall" for f in left.facets)
    rows = {
        r.axis: r
        for r in compare_features(
            (fact("ビジュアルプログラミング"),), (fact("ビジュアルプログラミング"),)
        )
    }
    assert rows["programming_method"].result == "common"


def test_home_activity_monitoring_accepts_numeric_living_alone_wording():
    left = classify_topic(content("高齢者見守り", "ひとり暮らしの安否確認。"), "left")
    right = classify_topic(content("高齢者見守り", "1人暮らしの安否確認。"), "right")
    assert not topic_reasons(topic_checks(left, right))


def test_visual_programming_spelling_variants_are_common_with_original_fact_references():
    left = fact("PCのブラウザ上のビジュアルプログラミング", "software_requirement")
    right = fact(
        "タブレットやスマートフォン上でのビジュアル・プログラミング", "software_requirement"
    )
    rows = {r.axis: r for r in compare_features((left,), (right,))}
    assert rows["programming_method"].result == "common"
    assert rows["programming_method"].target.fact_ids == (left.fact_id,)
    assert rows["programming_method"].candidate.fact_ids == (right.fact_id,)
    assert rows["software"].result == "different"


def test_radar_and_body_motion_sensor_methods_are_recorded_as_different():
    left = fact("ミリ波レーダーで心拍・呼吸を検知する")
    right = fact("マットレスの下に敷き、体動を検知するセンサーで心拍・呼吸を算出する")
    rows = {r.axis: r for r in compare_features((left,), (right,))}
    assert rows["sensing_method"].result == "different"
    assert rows["sensing_method"].candidate.fact_ids == (right.fact_id,)
    assert rows["observed_signals"].result == "common"


def test_edge_ai_topics_require_explicit_processing_and_keep_source_offsets():
    sources = (
        content("エッジAIコンピュータ", "Jetson AGX OrinによるAI処理をエッジ環境で行う。"),
        content("組込みエッジAIボード", "RZ/V2Hを用いたAI推論を行う。"),
    )
    topics = [classify_topic(source, "fixture") for source in sources]
    assert not topic_reasons(topic_checks(*topics))
    for source, topic in zip(sources, topics, strict=True):
        for facet in topic.facets:
            for evidence in facet.evidence:
                assert (
                    getattr(source, evidence.field)[evidence.start : evidence.end] == evidence.quote
                )
    vague = classify_topic(content("AI関連イベント", "新技術を紹介する。"), "vague")
    assert "TOPIC_FUNCTION_UNCONFIRMED" in topic_reasons(topic_checks(topics[0], vague))
    cloud = classify_topic(content("言語モデル", "クラウドでLLMを提供する。"), "cloud")
    assert "TOPIC_ENVIRONMENT_UNCONFIRMED" in topic_reasons(topic_checks(topics[0], cloud))


def test_ai_chip_axis_compares_recorded_families_without_ranking_performance():
    left, right = fact("NVIDIA Jetson AGX Orin"), fact("RZ/V2H")
    row = next(r for r in compare_features((left,), (right,)) if r.axis == "ai_processor")
    assert row.result == "different"
    assert row.target.fact_ids == (left.fact_id,)
    assert row.candidate.evidence_ids == (right.evidence_id,)
    unknown = next(
        r for r in compare_features((left,), (fact("高性能AI処理"),)) if r.axis == "ai_processor"
    )
    assert unknown.result == "unknown"
