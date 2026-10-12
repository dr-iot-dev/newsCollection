from uuid import uuid4

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.infrastructure.db.models import AiRun, AuditEvent, CandidateDecision, Fact, VerificationRun
from app.modules.rendering.model_disclosure import append_model_disclosure, with_image_model
from app.orchestration.model_disclosure import article_model_stages, recorded_model
from tests.unit.test_draft_exports import setup_publication


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


def test_publication_discloses_linked_runs_and_rejects_stale_provenance(
    acquisition_session, tmp_path
):
    session = acquisition_session
    item, draft, _author, _, _, config, _cms, _service = setup_publication(session, tmp_path)
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
    from app.orchestration.draft_exports import DraftExporter
    from nw_generation.protocol import read_bundle

    row = DraftExporter(session, config).export(draft.id)
    _, files = read_bundle(__import__("pathlib").Path(row.file_path), draft=True)
    content = files["article.html"].decode()
    assert "本文作成・編集: recorded-writer" in content
    assert "原稿のAI検証: recorded-verifier" in content
    assert "unused-newer-writer" not in content and config.ai_writer_model not in content


def test_fact_provenance_requires_exact_evidence_link(acquisition_session, tmp_path):
    session = acquisition_session
    item, draft, _, _, _, _, _, service = setup_publication(session, tmp_path)
    _, package = service.package(item)
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


def test_ai_fact_extraction_audit_links_the_actual_execution(acquisition_session, tmp_path):
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


def test_obsolete_note_is_removed_without_losing_actual_model_list():
    from app.modules.rendering.model_disclosure import OBSOLETE_NOTE, remove_obsolete_note

    original = append_model_disclosure("<p>本文</p>", [("本文作成・編集", "gpt-5.2")])
    assert OBSOLETE_NOTE not in original
    legacy = original + "<p>" + OBSOLETE_NOTE + "</p>"
    updated = with_image_model(legacy, "image_gen (model undisclosed)")
    assert OBSOLETE_NOTE not in updated
    assert "gpt-5.2" in updated and "<p>本文</p>" in updated
    assert remove_obsolete_note(updated) == updated


def test_opaque_image_model_uses_confirmed_host_version_for_exact_asset(
    acquisition_session, tmp_path
):
    from app.infrastructure.db.models import FeaturedImage
    from app.orchestration.editorial import touch
    from app.orchestration.model_disclosure import image_model_description

    session = acquisition_session
    item, draft, _author, _, _, _, _, _service = setup_publication(session, tmp_path)
    from app.infrastructure.db.models import Publication

    publication = Publication(
        item_id=item.id,
        draft_id=draft.id,
        target="historical-only",
        idempotency_key="fixture",
        payload_hash="sha256:" + "0" * 64,
        state="legacy",
    )
    session.add(publication)
    session.flush()
    image = FeaturedImage(
        publication_id=publication.id,
        draft_id=draft.id,
        model="gpt-image-1.5 / 色調整: imagegen (モデル名未提供)",
        prompt="recorded prompt",
        input_hash="sha256:" + "1" * 64,
        content_hash="sha256:" + "2" * 64,
    )
    session.add(image)
    touch(session, item, "image.asset_import_intent", content_hash=image.content_hash)
    session.flush()
    clean = "gpt-image-1.5 / 色調整: imagegen"
    assert image_model_description(session, image) == clean
    touch(
        session,
        item,
        "image.tool_software_identified",
        content_hash=image.content_hash,
        software_name="Codex",
        software_version="26.1007.21434",
    )
    session.flush()
    assert image_model_description(session, image) == (
        clean + "\uff08組み込み先: Codex 26.1007.21434\uff09"
    )
    image.content_hash = "sha256:" + "3" * 64
    assert image_model_description(session, image) == clean
    image.content_hash = None
    assert image_model_description(session, image) == clean
    image.model = "gpt-image-1.5"
    assert image_model_description(session, image) == "gpt-image-1.5"


def test_manual_edits_retain_matching_prior_ai_extraction_models(acquisition_session, tmp_path):
    from app.infrastructure.db.models import EvidencePackage
    from app.orchestration.editorial import touch

    session = acquisition_session
    item, draft, _, _, _, _, _, service = setup_publication(session, tmp_path)
    _, package = service.package(item)
    facts = list(session.scalars(select(Fact).where(Fact.id.in_(package.verified_fact_ids))))
    original = facts[0]
    evidence = session.get(EvidencePackage, original.evidence_package_id)
    evidence.revision = 10
    for fact in facts:
        fact.extractor = "manual"
    session.flush()

    def prior(revision, model, *, changed_conditions=False, invalid=False):
        parent = EvidencePackage(
            item_id=item.id,
            revision=revision,
            item_version=item.version,
            input_hash="sha256:" + str(revision).zfill(64),
            payload_json={},
            payload_hash="test",
        )
        session.add(parent)
        session.flush()
        value = dict(original.value_json)
        if changed_conditions:
            value["conditions"] = "different eligibility conditions"
        copied = Fact(
            item_id=item.id,
            item_version=item.version,
            evidence_package_id=parent.id,
            evidence_id=uuid4(),
            fact_type=original.fact_type,
            subject=original.subject,
            predicate=original.predicate,
            value_json=value,
            normalized_value=original.normalized_value,
            evidence_text=original.evidence_text,
            source_url=original.source_url,
            confidence=original.confidence,
            extractor="ai",
        )
        session.add(copied)
        run = add_run(session, item.id, "facts", model)
        if invalid:
            run.validation_status = "invalid"
        touch(
            session,
            item,
            "facts.extracted",
            evidence_package_id=str(parent.id),
            ai_run_id=str(run.id),
        )
        session.flush()

    prior(1, "initial-extractor")
    prior(2, "discarded-different-facts", changed_conditions=True)
    prior(3, "failed-extractor", invalid=True)
    prior(11, "unused-later-extractor")
    verification = session.scalars(
        select(VerificationRun).where(VerificationRun.draft_id == draft.id)
    ).one()
    description = dict(article_model_stages(session, draft, verification, package))["事実抽出"]
    assert description.startswith("initial-extractor ")
    assert "出典照合による編集" in description and "AI使用なし" not in description
    assert "discarded" not in description and "failed" not in description
    assert "unused-later" not in description


def test_manual_fact_edit_without_prior_record_does_not_claim_no_ai(acquisition_session, tmp_path):
    session = acquisition_session
    item, draft, _, _, _, _, _, service = setup_publication(session, tmp_path)
    _, package = service.package(item)
    for fact in session.scalars(select(Fact).where(Fact.id.in_(package.verified_fact_ids))):
        fact.extractor = "manual"
    session.flush()
    verification = session.scalars(
        select(VerificationRun).where(VerificationRun.draft_id == draft.id)
    ).one()
    description = dict(article_model_stages(session, draft, verification, package))["事実抽出"]
    assert "記録なし" in description and "AI使用なし" not in description
