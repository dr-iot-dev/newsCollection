from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.ai.provider import AIResponse
from app.ai.runner import AIRunner
from app.api.auth import create_user
from app.contracts.envelope import canonical_payload_hash
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    ArticleDraft,
    ArticlePackage,
    ExtractionResult,
    Item,
    ItemStatus,
    LegalStatus,
    ModuleMessage,
    Source,
)
from app.modules.acquisition.service import CollectionResult
from app.modules.research.service import relevance_score
from app.orchestration.editorial import EditorialService, process_editorial_outbox
from app.orchestration.editorial_jobs import EditorialJobRequest, process_editorial_jobs, queue_job
from app.orchestration.phase2 import process_phase2
from app.orchestration.research import prepare_comparison, process_comparison_research
from tests.unit.test_acquisition_service import RSS
from tests.unit.test_phase2_pipeline import collect
from tests.unit.test_phase3 import Provider, settings


def add_article(session, key, company, product, spec, price, day, kind="gateway"):
    body = (
        f"Company: {company}\nProduct: {product}\n仕様: {spec}GB\n価格: {price}円\n"
        f"発売日: 2026年11月\n" + f"The manufacturer released an edge AI {kind} with a documented "
        f"local interface for industrial installations. The {product} includes a primary release "
        "description with technical requirements and deployment conditions. " * 3
    )
    data = RSS.replace(b"release-1", key.encode()).replace(b"/news/one", f"/news/{key}".encode())
    description = {
        "previous": "legacy industrial device deployment gateway specification",
        "future": "next generation industrial device gateway announcement",
        "second": "manufacturer detailed industrial gateway technical reference",
    }.get(key, f"edge AI {kind}")
    data = data.replace(b"Product released", f"{company} {product} {description}".encode())
    data = data.replace(b"Feature one", body.encode()).replace(b"30 Sep", f"{day} Sep".encode())
    collect(session, data)
    process_phase2(session)
    session.commit()
    item = session.scalar(select(Item).where(Item.external_id == key))
    assert item.duplicate_of_id is None
    assert item.status == ItemStatus.DEDUPED
    return item


def seed_articles(session):
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    previous = add_article(session, "previous", "ExampleCorp", "ABC90", 4, "12,800", 29)
    competitor = add_article(session, "competitor", "OtherCorp", "XYZ200", 16, "29,800", 30)
    return target, previous, competitor


class ComparisonProvider(Provider):
    def generate(self, **kwargs):
        if kwargs["model"] == "writer-test":
            data = kwargs["data"]
            self.calls.append((kwargs["model"], data, kwargs["instructions"]))
            return AIResponse(
                {
                    "title": "ゲートウェイの比較",
                    "lead": "確認できた仕様と条件を整理します。",
                    "paragraphs": [
                        {
                            "text": "仕様は8GBです。",
                            "fact_ids": [f["fact_id"] for f in data["facts"]],
                        }
                    ],
                    "category_keys": ["edge_ai"],
                    "importance": 3,
                    "previous_comparison": comparison_text(data, "previous_products"),
                    "competitor_comparison": comparison_text(data, "competitor_products"),
                },
                "writer-response",
                10,
                5,
                1,
            )
        return super().generate(**kwargs)


def comparison_text(data, relation):
    values = data["comparison"][relation]
    if values[0]["unavailable_reason"]:
        return ""
    kind = "同社の従来製品" if relation == "previous_products" else "他社の製品"
    return (
        kind
        + "について、"
        + "。".join(f"{v['subject']}:{v['value']}。{v['conditions']}" for v in values)
    )


def svc(session, config=None, provider=None, actor=None):
    config = config or settings().model_copy(update={"research_refresh_sources": False})
    return EditorialService(
        session, config, AIRunner(session, config, provider or ComparisonProvider()), actor
    )


def prepared_root(session, target, config=None):
    service = svc(session, config)
    assert service.facts(target.id)
    assert service.select(target.id).decision == "selected"
    session.commit()
    return service


def install_factory(monkeypatch, provider=None):
    monkeypatch.setattr(
        "app.orchestration.editorial_jobs.EditorialService",
        lambda db, cfg, actor_id: svc(db, cfg, provider, actor_id),
    )


def test_pipeline_searches_both_relations_and_completes_verified_draft(
    acquisition_session, monkeypatch
):
    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    actor, _ = create_user(session, "writer", ["editor"])
    config = settings().model_copy(update={"research_refresh_sources": False})
    job = queue_job(
        session,
        target.id,
        "pipeline",
        EditorialJobRequest(expected_version=target.workflow_version),
        actor.id,
    )
    session.commit()
    install_factory(monkeypatch)
    assert process_editorial_jobs(session, config) == 1
    session.commit()
    assert job.status == "success" and job.stats_json["result"]["status"] == "pass"
    package = session.get(ArticlePackage, UUID(job.stats_json["result"]["article_package_id"]))
    assert {r["reference_id"] for r in package.payload_json["source_references"]} == {
        str(target.id),
        str(previous.id),
        str(competitor.id),
    }
    assert all(v["evidence_id"] for v in package.payload_json["comparison"]["previous_products"])
    assert all(v["evidence_id"] for v in package.payload_json["comparison"]["competitor_products"])
    draft = session.get(ArticleDraft, UUID(job.stats_json["result"]["draft_id"]))
    assert "ABC90" in draft.body_markdown and "XYZ200" in draft.body_markdown
    assert target.status == ItemStatus.REVIEW_PENDING
    messages = list(
        session.scalars(
            select(ModuleMessage).where(ModuleMessage.consumer == "acquisition_research")
        )
    )
    assert len(messages) == 2 and all(m.status == "processed" for m in messages)
    assert all(m.result_json["article_package_id"] == str(package.id) for m in messages)
    # Pending comparison outbox events must not replace the selected references.
    process_editorial_outbox(session, config, "comparison")
    session.commit()
    assert session.get(ArticlePackage, package.id).payload_json["comparison"][
        "competitor_products"
    ][0]["evidence_id"]
    assert session.scalars(
        select(ArticlePackage).where(ArticlePackage.item_id == target.id)
    ).all() == [package]


def test_ineligible_or_unrelated_candidates_are_not_used(acquisition_session):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    future = add_article(session, "future", "ExampleCorp", "ABC110", 16, "22,800", 30)
    unrelated = add_article(
        session, "unrelated", "OtherCorp", "Database200", 4, "8,800", 28, "database"
    )
    service = prepared_root(session, target)
    prepared = prepare_comparison(service, target.id)
    assert prepared.previous_ids == prepared.competitor_ids == ()
    assert not prepared.pending
    results = [session.get(ModuleMessage, key).result_json for key in prepared.request_ids]
    assert any(
        r["code"] == "PREVIOUS_PRODUCT_DATE_UNCONFIRMED"
        for result in results
        for r in result["rejected"]
    )
    assert str(unrelated.id) not in {v["item_id"] for result in results for v in result["selected"]}
    assert future.id != target.id


def test_manual_references_are_preserved_and_missing_relation_is_searched(acquisition_session):
    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    service = prepared_root(session, target)
    service.facts(previous.id)
    prepared = prepare_comparison(service, target.id, (previous.id,))
    assert prepared.previous_ids == (previous.id,)
    assert prepared.competitor_ids == (competitor.id,)
    assert len(prepared.request_ids) == 1


def test_missing_references_complete_with_explicit_unavailable_reason(
    acquisition_session, monkeypatch
):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    actor, _ = create_user(session, "writer", ["editor"])
    job = queue_job(
        session,
        target.id,
        "pipeline",
        EditorialJobRequest(expected_version=target.workflow_version),
        actor.id,
    )
    session.commit()
    install_factory(monkeypatch)
    process_editorial_jobs(
        session, settings().model_copy(update={"research_refresh_sources": False})
    )
    session.commit()
    assert job.stats_json["result"]["status"] == "pass"
    draft = session.get(ArticleDraft, UUID(job.stats_json["result"]["draft_id"]))
    assert "比較不能" not in draft.body_markdown
    assert "## 他製品との比較" not in draft.body_markdown
    package = session.get(ArticlePackage, draft.article_package_id)
    assert package.payload_json["comparison"]["previous_products"][0]["unavailable_reason"]
    assert package.payload_json["comparison"]["competitor_products"][0]["unavailable_reason"]
    messages = session.scalars(
        select(ModuleMessage).where(ModuleMessage.consumer == "acquisition_research")
    ).all()
    assert all(
        m.status == "unavailable" and m.error_json["code"] == "NO_VERIFIED_COMPARISON_FOUND"
        for m in messages
    )


def test_source_refresh_discovers_candidates_and_obeys_approved_scope(
    acquisition_session, monkeypatch
):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    service = prepared_root(session, target, settings())
    github = session.scalar(select(Source).where(Source.key == "github-esphome"))
    github.legal_status = LegalStatus.BLOCKED
    seen = []

    def refresh(db, key, **kwargs):
        seen.append(key)
        add_article(db, "previous", "ExampleCorp", "ABC90", 4, "12,800", 29)
        add_article(db, "competitor", "OtherCorp", "XYZ200", 16, "29,800", 30)
        return CollectionResult(key, "success", created=2)

    monkeypatch.setattr("app.orchestration.research.collect_source", refresh)
    prepared = prepare_comparison(service, target.id)
    assert len(prepared.previous_ids) == len(prepared.competitor_ids) == 1
    assert seen == ["vendor-official-feed"]
    assert not prepared.pending


def test_transient_research_retry_resumes_the_same_job_and_stale_edit_blocks_it(
    acquisition_session, monkeypatch
):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    actor, _ = create_user(session, "writer", ["editor"])
    job = queue_job(
        session,
        target.id,
        "pipeline",
        EditorialJobRequest(expected_version=target.workflow_version),
        actor.id,
    )
    session.commit()
    install_factory(monkeypatch)
    monkeypatch.setattr(
        "app.orchestration.research.collect_source",
        lambda db, key, **kw: CollectionResult(key, "failed", error_code="HTTP_ERROR"),
    )
    config = settings().model_copy(update={"research_max_attempts": 2})
    assert process_editorial_jobs(session, config) == 1
    session.commit()
    assert job.status == "waiting_research" and job.finished_at is None
    assert session.scalars(select(ArticleDraft)).first() is None
    assert process_editorial_jobs(session, config) == 0
    # The normal scheduler must not take ownership from a waiting explicit job.
    workflow = target.workflow_version
    process_editorial_outbox(session, config, "selection")
    process_editorial_outbox(session, config, "comparison")
    assert process_comparison_research(session, config) == 0
    session.commit()
    assert target.workflow_version == workflow
    assert session.scalars(select(ArticleDraft)).first() is None
    assert (
        len(
            session.scalars(
                select(ModuleMessage).where(ModuleMessage.consumer == "acquisition_research")
            ).all()
        )
        == 2
    )
    add_article(session, "previous", "ExampleCorp", "ABC90", 4, "12,800", 29)
    add_article(session, "competitor", "OtherCorp", "XYZ200", 16, "29,800", 30)
    job.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
    for message in session.scalars(
        select(ModuleMessage).where(ModuleMessage.consumer == "acquisition_research")
    ):
        message.available_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert process_editorial_jobs(session, config) == 1
    session.commit()
    assert job.status == "success" and job.attempt == 2
    assert job.stats_json["result"]["status"] == "pass"
    # A newly waiting job cannot override a human edit or approval.
    waiting = queue_job(
        session,
        target.id,
        "comparison",
        EditorialJobRequest(expected_version=target.workflow_version),
        actor.id,
    )
    waiting.status = "waiting_research"
    waiting.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
    target.workflow_version += 1
    session.commit()
    process_editorial_jobs(session, config)
    assert waiting.status == "failed" and waiting.error_code == "VERSION_CONFLICT"


def test_retry_budget_finishes_without_inventing_comparisons(acquisition_session, monkeypatch):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    service = prepared_root(
        session, target, settings().model_copy(update={"research_max_attempts": 1})
    )
    monkeypatch.setattr(
        "app.orchestration.research.collect_source",
        lambda db, key, **kw: CollectionResult(key, "failed", error_code="HTTP_ERROR"),
    )
    prepared = prepare_comparison(service, target.id)
    assert not prepared.pending and prepared.previous_ids == prepared.competitor_ids == ()
    assert all(
        session.get(ModuleMessage, key).error_json["code"] == "SEARCH_BUDGET_EXHAUSTED"
        for key in prepared.request_ids
    )


def test_revoked_source_invalidates_cached_research_selection(acquisition_session):
    session = acquisition_session
    target, previous, _ = seed_articles(session)
    service = prepared_root(session, target)
    prepared = prepare_comparison(service, target.id)
    assert prepared.previous_ids == (previous.id,)
    source = session.get(Source, previous.source_id)
    source.enabled = False
    with pytest.raises(EditorialError, match="SOURCE_RIGHTS_BLOCKED"):
        prepare_comparison(service, target.id)


def test_research_outbox_completes_existing_package_and_protects_manual_drafts(
    acquisition_session, monkeypatch
):
    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    service = prepared_root(session, target)
    initial = service.comparison(target.id)
    session.commit()
    monkeypatch.setattr("app.orchestration.research.EditorialService", lambda db, cfg: svc(db, cfg))
    config = settings().model_copy(update={"research_refresh_sources": False})
    assert process_comparison_research(session, config) == 1
    session.commit()
    packages = session.scalars(
        select(ArticlePackage)
        .where(ArticlePackage.item_id == target.id)
        .order_by(ArticlePackage.revision)
    ).all()
    assert len(packages) == 2 and packages[-1].id != initial.id
    assert {value["reference_id"] for value in packages[-1].payload_json["source_references"]} == {
        str(target.id),
        str(previous.id),
        str(competitor.id),
    }
    assert process_comparison_research(session, config) == 0
    # A new pending research message cannot rewrite a manually created draft.
    second = add_article(session, "second", "ExampleCorp", "ABC200", 8, "39,800", 30)
    second_service = prepared_root(session, second)
    second_service.comparison(second.id)
    draft = second_service.draft(second.id)
    session.commit()
    assert process_comparison_research(session, config) == 0
    assert (
        draft.id
        == session.scalars(select(ArticleDraft).where(ArticleDraft.item_id == second.id)).one().id
    )
    assert all(
        message.status == "superseded"
        for message in session.scalars(
            select(ModuleMessage).where(
                ModuleMessage.consumer == "acquisition_research",
                ModuleMessage.payload_json["item_id"].as_string() == str(second.id),
            )
        )
    )


def test_invalid_reference_payload_does_not_block_other_candidates(acquisition_session):
    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    extraction = session.scalar(
        select(ExtractionResult).where(ExtractionResult.item_id == previous.id)
    )
    extraction.payload_json = {**extraction.payload_json, "body_sha256": "invalid"}
    extraction.payload_hash = canonical_payload_hash(extraction.payload_json)
    service = prepared_root(session, target)
    prepared = prepare_comparison(service, target.id)
    assert prepared.previous_ids == ()
    assert prepared.competitor_ids == (competitor.id,)
    assert any(
        r["code"] == "REFERENCE_SOURCE_OR_EXTRACTION_INVALID"
        for key in prepared.request_ids
        for r in session.get(ModuleMessage, key).result_json["rejected"]
    )


def test_failed_waiting_job_cleans_up_owned_research(acquisition_session, monkeypatch):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30)
    actor, _ = create_user(session, "writer", ["editor"])
    job = queue_job(
        session,
        target.id,
        "pipeline",
        EditorialJobRequest(expected_version=target.workflow_version),
        actor.id,
    )
    session.commit()
    install_factory(monkeypatch)
    monkeypatch.setattr(
        "app.orchestration.research.collect_source",
        lambda db, key, **kw: CollectionResult(key, "failed", error_code="HTTP_ERROR"),
    )
    config = settings()
    process_editorial_jobs(session, config)
    session.commit()
    assert job.status == "waiting_research"
    target.workflow_version += 1
    job.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    process_editorial_jobs(session, config)
    assert job.status == "failed" and job.error_code == "VERSION_CONFLICT"
    messages = session.scalars(
        select(ModuleMessage).where(ModuleMessage.consumer == "acquisition_research")
    ).all()
    assert len(messages) == 2
    assert all(
        m.status == "blocked" and m.error_json["code"] == "VERSION_CONFLICT" for m in messages
    )


def test_auto_research_opt_out_stays_manual_even_in_scheduler(acquisition_session, monkeypatch):
    session = acquisition_session
    target, _, _ = seed_articles(session)
    actor, _ = create_user(session, "writer", ["editor"])
    job = queue_job(
        session,
        target.id,
        "pipeline",
        EditorialJobRequest(expected_version=target.workflow_version, auto_research=False),
        actor.id,
    )
    session.commit()
    install_factory(monkeypatch)
    config = settings().model_copy(update={"research_refresh_sources": False})
    process_editorial_jobs(session, config)
    session.commit()
    assert job.stats_json["result"]["status"] == "pass"
    process_editorial_outbox(session, config, "comparison")
    assert process_comparison_research(session, config) == 0
    assert not session.scalars(
        select(ModuleMessage).where(ModuleMessage.consumer == "acquisition_research")
    ).all()
    package = session.get(ArticlePackage, UUID(job.stats_json["result"]["article_package_id"]))
    assert package.payload_json["comparison"]["competitor_products"][0]["unavailable_reason"]


def test_matching_sensors_do_not_make_educational_boards_caregiving_competitors(
    acquisition_session,
):
    session = acquisition_session
    target = add_article(session, "target", "ExampleCorp", "ABC100", 8, "19,800", 30, "sensor")
    service = prepared_root(session, target)
    _, evidence = service.evidence(target)
    assert (
        relevance_score(evidence, "介護施設の見守りセンサー", "学習用教材", "工作用のsensor camera")
        == 0
    )
    assert (
        relevance_score(evidence, "介護施設の見守りセンサー", "高齢者向けサービス", "見守りsensor")
        > 0
    )


def test_available_comparison_cannot_claim_unavailable_even_if_other_section_is_missing(
    acquisition_session,
):
    from app.contracts.draft_v1 import ArticleDraftV1
    from app.contracts.editorial_v1 import WritingOutputV1
    from app.modules.verification.service import rule_criteria
    from app.modules.writing.service import validate_writing

    session = acquisition_session
    target, previous, _competitor = seed_articles(session)
    service = prepared_root(session, target)
    service.facts(previous.id)
    prepared = prepare_comparison(service, target.id, (previous.id,))
    service.comparison(
        target.id, prepared.previous_ids, prepared.competitor_ids, request_missing=False
    )
    _, package = service.package(target)
    data = package.model_dump(mode="json")
    output = WritingOutputV1.model_validate(
        ComparisonProvider()
        .generate(
            model="writer-test", data=data, instructions="", schema={}, max_output_tokens=4000
        )
        .output
    )
    invalid = output.model_copy(update={"competitor_comparison": "比較対象未確認のため比較不能。"})
    with pytest.raises(EditorialError, match="DRAFT_COMPARISON_CONTENT_MISSING"):
        validate_writing(invalid, package)
    draft = service.draft(target.id, manual=output)
    dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
    dto = dto.model_copy(
        update={
            "body_markdown": dto.body_markdown.replace(
                output.competitor_comparison, invalid.competitor_comparison
            )
        }
    )
    criteria = {c.key: c.result for c in rule_criteria(dto, package)}
    assert criteria["competitor_comparison"] == "fail"


@pytest.mark.parametrize(
    "use_previous,use_competitor", [(False, False), (True, False), (False, True), (True, True)]
)
def test_unified_comparison_only_renders_verified_relations(
    acquisition_session, use_previous, use_competitor
):
    from app.contracts.draft_v1 import ArticleDraftV1
    from app.contracts.editorial_v1 import WritingOutputV1
    from app.modules.verification.service import rule_criteria
    from app.modules.writing.service import validate_writing

    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    service = prepared_root(session, target)
    service.facts(previous.id)
    service.facts(competitor.id)
    service.comparison(
        target.id,
        (previous.id,) if use_previous else (),
        (competitor.id,) if use_competitor else (),
        request_missing=False,
    )
    _, package = service.package(target)
    output = WritingOutputV1.model_validate(
        ComparisonProvider()
        .generate(
            model="writer-test",
            data=package.model_dump(mode="json"),
            instructions="",
            schema={},
            max_output_tokens=4000,
        )
        .output
    )
    draft = service.draft(target.id, manual=output)
    dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
    assert "## 他製品との比較" not in dto.body_markdown
    assert "## 従来製品との比較" not in dto.body_markdown
    assert "## 他社製品との比較" not in dto.body_markdown
    assert "比較不能" not in dto.body_markdown
    assert dto.body_markdown.count("同社の従来製品について") == int(use_previous)
    assert dto.body_markdown.count("他社の製品について") == int(use_competitor)
    assert "を比較対象にします。" not in dto.body_markdown
    criteria = {c.key: c.result for c in rule_criteria(dto, package)}
    assert criteria["previous_comparison"] == criteria["competitor_comparison"] == "pass"
    assert "title_clarity" in criteria
    for available, values, field in (
        (use_previous, package.comparison.previous_products, "previous_comparison"),
        (
            use_competitor,
            package.comparison.competitor_products,
            "competitor_comparison",
        ),
    ):
        if available:
            # Missing comparison prose must fail without an automatic introduction.
            missing = dto.model_copy(
                update={"body_markdown": dto.body_markdown.replace(getattr(output, field), "")}
            )
            assert {c.key: c.result for c in rule_criteria(missing, package)}[field] == "fail"
        else:
            assert values[0].unavailable_reason
            invalid = output.model_copy(update={field: values[0].unavailable_reason})
            with pytest.raises(EditorialError, match="DRAFT_COMPARISON_CONTENT_MISSING"):
                validate_writing(invalid, package)
    with pytest.raises(EditorialError, match="DRAFT_TITLE_TOO_LONG"):
        validate_writing(output.model_copy(update={"title": "長" * 61}), package)


@pytest.mark.parametrize("relation", ["previous", "competitor", "both"])
def test_writer_integrates_comparisons_into_fact_mapped_body(acquisition_session, relation):
    from app.contracts.draft_v1 import ArticleDraftV1
    from app.contracts.editorial_v1 import WritingOutputV1
    from app.modules.verification.service import rule_criteria
    from app.modules.writing.service import validate_writing

    session = acquisition_session
    target, previous, competitor = seed_articles(session)
    service = prepared_root(session, target)
    service.facts(previous.id)
    service.facts(competitor.id)
    service.comparison(
        target.id,
        (previous.id,) if relation != "competitor" else (),
        (competitor.id,) if relation != "previous" else (),
        request_missing=False,
    )
    _, package = service.package(target)
    data = package.model_dump(mode="json")
    output = WritingOutputV1.model_validate(
        ComparisonProvider()
        .generate(
            model="writer-test", data=data, instructions="", schema={}, max_output_tokens=4000
        )
        .output
    )
    paragraphs = [*output.paragraphs]
    for text in [output.previous_comparison, output.competitor_comparison]:
        if text:
            paragraphs.append({"text": text, "fact_ids": package.verified_fact_ids})
    integrated = WritingOutputV1.model_validate(
        {
            **output.model_dump(mode="json"),
            "paragraphs": paragraphs,
            "previous_comparison": "",
            "competitor_comparison": "",
        }
    )
    validate_writing(integrated, package)
    draft = service.draft(target.id, manual=integrated)
    dto = ArticleDraftV1.model_validate(draft.source_block["draft"])
    assert "## 他製品との比較" not in dto.body_markdown
    assert len(dto.paragraph_facts) == len(paragraphs)
    assert all(c.result == "pass" for c in rule_criteria(dto, package))
    for heading in ["## 他製品との比較", "## 従来製品との比較", "## 他社製品との比較"]:
        invalid = integrated.model_copy(update={"lead": heading + "\n" + integrated.lead})
        with pytest.raises(EditorialError, match="DRAFT_COMPARISON_SECTION_FORBIDDEN"):
            validate_writing(invalid, package)
        altered = dto.model_copy(update={"lead": heading + "\n" + dto.lead})
        criteria = {c.key: c.result for c in rule_criteria(altered, package)}
        assert criteria["previous_comparison"] == criteria["competitor_comparison"] == "fail"
