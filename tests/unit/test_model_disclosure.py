from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.contracts.envelope import canonical_payload_hash
from app.contracts.wordpress_v1 import WordPressRequestV1
from app.core.editorial import EditorialError
from app.infrastructure.db.models import AiRun, AuditEvent, CandidateDecision, Fact, VerificationRun
from app.modules.publication.model_disclosure import append_model_disclosure, with_image_model
from app.orchestration.model_disclosure import article_model_stages, recorded_model
from tests.unit.test_phase4 import setup_publication


def add_run(session, item_id, role, model):
    run = AiRun(
        item_id=item_id,
        task_type=role,
        execution_role=role,
        provider="openai",
        model=model,
        model_profile_key=role + "-default",
        prompt_version="test-v1",
        input_hash="sha256:" + "0" * 64,
        validation_status="valid",
        output_json={},
    )
    session.add(run)
    session.flush()
    return run


def test_disclosure_is_canonical_escaped_and_preserves_sources_and_table():
    body = (
        "<p>本文である。</p><table><tr><td>資料1</td></tr></table>"
        "<h2>出典</h2><ul><li>資料1: URL</li></ul>"
    )
    forged = body + "<h2>使用したAIモデル</h2><ul><li>架空のモデル</li></ul>"
    stages = [("本文作成・編集", "<script>wrong</script>"), ("原稿のAI検証", "actual-verifier")]
    content = append_model_disclosure(forged, stages)
    soup = BeautifulSoup(content, "html.parser")
    assert not soup.find("script") and "架空のモデル" not in soup.get_text()
    assert [h.get_text() for h in soup.find_all("h2")] == ["出典", "使用したAIモデル"]
    assert soup.find("table").get_text() == "資料1"
    image_content = with_image_model(content, "actual-image")
    assert with_image_model(image_content, "actual-image") == image_content
    assert image_content.count("画像生成: actual-image") == 1
    assert (
        image_content.split("<h2>使用したAIモデル</h2>")[0]
        == content.split("<h2>使用したAIモデル</h2>")[0]
    )


def test_publication_discloses_linked_runs_and_rejects_stale_provenance(acquisition_session):
    session = acquisition_session
    item, draft, author, _, _, config, cms, service = setup_publication(session)
    writing = add_run(session, item.id, "writer", "recorded-writer")
    draft.ai_run_id = writing.id
    verification = session.scalars(
        select(VerificationRun).where(VerificationRun.draft_id == draft.id)
    ).one()
    verifier = session.get(AiRun, verification.ai_run_id)
    verifier.provider, verifier.model = "openai", "recorded-verifier"
    # A newer unrelated run and the current profile must never overwrite article provenance.
    add_run(session, item.id, "writer", "unused-newer-writer")
    session.commit()
    row = service.create_draft(
        item.id,
        WordPressRequestV1(expected_version=item.workflow_version, draft_id=draft.id),
        author.id,
    )
    content = row.payload_json["content"]
    assert "本文作成・編集: recorded-writer" in content
    assert "原稿のAI検証: recorded-verifier" in content
    assert "unused-newer-writer" not in content and config.ai_writer_model not in content
    assert row.payload_hash == canonical_payload_hash(row.payload_json)
    service.validate_package(item, row)
    verifier.model = "changed-record"
    session.flush()
    with pytest.raises(EditorialError, match="PUBLICATION_PACKAGE_STALE"):
        service.validate_package(item, row)
    assert len(cms.writes) == 1


def test_fact_provenance_requires_exact_evidence_link(acquisition_session):
    session = acquisition_session
    item, draft, _, _, _, _, _, service = setup_publication(session)
    _, package = service.editorial.package(item)
    verification = session.scalars(
        select(VerificationRun).where(VerificationRun.draft_id == draft.id)
    ).one()
    facts = list(session.scalars(select(Fact).where(Fact.id.in_(package.verified_fact_ids))))
    for fact in facts:
        fact.extractor = "ai"
    fact_run = add_run(session, item.id, "facts", "used-facts")
    unused = add_run(session, item.id, "facts", "unused-facts")
    extraction_event = next(
        event
        for event in session.scalars(
            select(AuditEvent).where(AuditEvent.action == "facts.extracted")
        )
        if event.after_json["evidence_package_id"] == str(facts[0].evidence_package_id)
    )
    extraction_event.after_json = {**extraction_event.after_json, "ai_run_id": str(fact_run.id)}
    candidate = session.get(CandidateDecision, package.candidate_id)
    candidate.ai_run_id = add_run(session, item.id, "selector", "used-selector").id
    draft.ai_run_id = None
    session.flush()
    stages = dict(article_model_stages(session, draft, verification, package))
    assert stages["事実抽出"] == "used-facts"
    assert stages["記事候補の選定"] == "used-selector"
    assert "記録なし" in stages["本文作成・編集"]
    extraction_event.after_json = {"facts": len(facts)}
    session.flush()
    assert (
        dict(article_model_stages(session, draft, verification, package))["事実抽出"]
        == "モデルの記録なし"
    )
    assert recorded_model(session, unused.id, uuid4(), "facts") == "モデルの記録なし"
    assert recorded_model(session, fact_run.id, item.id, "writer") == "モデルの記録なし"


def test_ai_fact_extraction_audit_links_the_actual_execution(acquisition_session):
    from app.ai.provider import AIResponse
    from app.contracts.content_v1 import NormalizedContentV1
    from app.infrastructure.db.models import ExtractionResult
    from app.modules.extraction.facts import rule_facts
    from app.orchestration.editorial import checked_payload
    from tests.unit.test_phase3 import prepared

    session = acquisition_session
    item, service, _ = prepared(session)
    extraction = session.scalar(select(ExtractionResult).where(ExtractionResult.item_id == item.id))
    output = rule_facts(checked_payload(extraction, NormalizedContentV1))

    class FactsProvider:
        def generate(self, **kwargs):
            return AIResponse(output.model_dump(mode="json"), "facts-request", 10, 10, 1)

    service.runner.provider = FactsProvider()
    evidence = service.facts(item.id, "ai")
    session.flush()
    event = next(
        event
        for event in session.scalars(
            select(AuditEvent).where(AuditEvent.action == "facts.extracted")
        )
        if event.after_json["evidence_package_id"] == str(evidence.id)
    )
    run = session.get(AiRun, __import__("uuid").UUID(event.after_json["ai_run_id"]))
    assert run.item_id == item.id and run.execution_role == "facts"
    assert run.model == "facts-test" and run.validation_status == "valid"
