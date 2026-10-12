from uuid import uuid4

import pytest
from sqlalchemy import select

from app.ai.provider import AIResponse
from app.ai.runner import AIRunner
from app.contracts.comparison_selection_v1 import (
    INDEPENDENT_CHECKS,
    ComparisonSuitabilityCheckV1,
    ComparisonSuitabilityOutputV1,
)
from app.contracts.envelope import canonical_payload_hash
from app.core.editorial import EditorialError
from app.infrastructure.db.models import (
    AiRun,
    ArticleDraft,
    ArticlePackage,
    ExtractionResult,
    Item,
    ModuleMessage,
    Publication,
)
from app.orchestration.comparison_selection import ComparisonSelectionService
from tests.unit.test_comparison_research import prepared_root, seed_articles
from tests.unit.test_comparison_selection import evaluation, plan


class ShadowProvider:
    def __init__(self, intent, sources, reject=False, fail_review=False, transient=False):
        self.intent, self.sources = intent, sources
        self.reject, self.fail_review = reject, fail_review
        self.transient = transient
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["model"] == "planner-test":
            output = self.intent
        elif kwargs["model"] == "assessor-test":
            if self.transient:
                raise EditorialError("AI_QUOTA_TEMPORARY")
            data = kwargs["data"]["source"]["document"]
            source = next(s for s in self.sources if str(s.document.item_id) == data["item_id"])
            output = evaluation(source, self.intent).evaluation
            if self.reject and source != self.sources[0]:
                output = output.model_copy(update={"decision": "rejected", "role_fit": "fail"})
        else:
            output = ComparisonSuitabilityOutputV1(
                checks=tuple(
                    ComparisonSuitabilityCheckV1(
                        key=k,
                        result="fail" if self.fail_review else "pass",
                        reason="Fixture review",
                        fact_ids=(self.sources[0].evidence.verified_facts[0].fact_id,),
                    )
                    for k in INDEPENDENT_CHECKS
                ),
                blocking_issues=("Different roles",) if self.fail_review else (),
            )
        data = output.model_dump(mode="json")
        if kwargs["model"] == "planner-test":
            for field in ("product", "product_kind", "role", "audience", "environment", "purpose"):
                judgment = data[field]
                judgment["fact_ids"] = [a["fact_id"] for a in judgment.pop("evidence")]
        elif kwargs["model"] == "assessor-test":
            data["reason"]["fact_ids"] = [a["fact_id"] for a in data["reason"].pop("evidence")]
            for cell in data["cells"]:
                cell["fact_ids"] = [a["fact_id"] for a in cell.pop("evidence")]
        return AIResponse(data, "fixture", 100, 20, 1)


def prepared(session, **provider_kwargs):
    target, previous, competitor = seed_articles(session)
    legacy = prepared_root(session, target)
    legacy.facts(previous.id)
    legacy.facts(competitor.id)
    session.commit()
    settings = legacy.settings.model_copy(
        update={
            "comparison_selection_mode": "shadow",
            "ai_comparison_planner_model": "planner-test",
            "ai_comparison_assessor_model": "assessor-test",
            "ai_comparison_verifier_model": "independent-test",
            "comparison_min_products": 3,
            "comparison_min_sources": 3,
        }
    )
    service = ComparisonSelectionService(session, settings)
    sources = [service.source(i.id) for i in (target, previous, competitor)]
    provider = ShadowProvider(plan(sources[0]), sources, **provider_kwargs)
    service.runner = AIRunner(session, settings, provider)
    return service, sources, provider


def test_shadow_saves_append_only_audit_and_reuses_completed_stages(acquisition_session):
    session = acquisition_session
    service, sources, provider = prepared(session)
    statuses = {s.document.item_id: session.get(Item, s.document.item_id).status for s in sources}
    ids = tuple(s.document.item_id for s in sources)
    audit = service.evaluate(ids[0], ids[1:])
    session.commit()
    assert audit.outcome == "eligible" and len(provider.calls) == 5
    repeat = service.evaluate(ids[0], ids[1:])
    assert audit == repeat and len(provider.calls) == 5
    for model in (ArticlePackage, ArticleDraft, Publication):
        assert session.scalar(select(model)) is None
    assert statuses == {key: session.get(Item, key).status for key in ids}
    assert (
        len(
            list(
                session.scalars(
                    select(ModuleMessage).where(
                        ModuleMessage.consumer == "comparison_selection_audit"
                    )
                )
            )
        )
        == 1
    )
    assert all(
        run.token_in == 100
        for run in session.scalars(select(AiRun).where(AiRun.execution_role.like("comparison_%")))
    )


@pytest.mark.parametrize("reject,fail_review", [(True, False), (False, True)])
def test_role_mismatch_or_independent_failure_defers_without_drafting(
    acquisition_session,
    reject,
    fail_review,
):
    service, sources, provider = prepared(
        acquisition_session, reject=reject, fail_review=fail_review
    )
    ids = tuple(s.document.item_id for s in sources)
    audit = service.evaluate(ids[0], ids[1:])
    assert audit.outcome == "deferred"
    assert acquisition_session.scalar(select(ArticleDraft)) is None
    assert len(provider.calls) == (4 if reject else 5)


def test_independent_model_configuration_and_budget_fail_before_ai(acquisition_session):
    service, sources, provider = prepared(acquisition_session)
    ids = tuple(s.document.item_id for s in sources)
    service.settings = service.settings.model_copy(
        update={"ai_comparison_verifier_model": "assessor-test"}
    )
    service.runner.settings = service.settings
    with pytest.raises(EditorialError, match="COMPARISON_INDEPENDENT_MODEL_REQUIRED"):
        service.evaluate(ids[0], ids[1:])
    service.runner.settings = service.settings.model_copy(
        update={"ai_comparison_verifier_model": "independent-test"}
    )
    service.settings = service.runner.settings.model_copy(update={"comparison_max_evaluations": 1})
    with pytest.raises(EditorialError, match="COMPARISON_EVALUATION_BUDGET_EXCEEDED"):
        service.evaluate(ids[0], ids[1:])
    assert not provider.calls


def test_changed_extraction_invalidates_cached_plan_and_evaluations(acquisition_session):
    session = acquisition_session
    service, sources, provider = prepared(session)
    ids = tuple(s.document.item_id for s in sources)
    first = service.evaluate(ids[0], ids[1:])
    row = session.scalar(select(ExtractionResult).where(ExtractionResult.item_id == ids[0]))
    row.payload_json = {**row.payload_json, "title": "Updated source title"}
    row.payload_hash = canonical_payload_hash(row.payload_json)
    session.flush()
    second = service.evaluate(ids[0], ids[1:])
    assert first.plan.plan_id != second.plan.plan_id and second.plan.revision == 2
    assert len(provider.calls) == 10


def test_tampered_stage_cache_is_rejected(acquisition_session):
    service, sources, _ = prepared(acquisition_session)
    ids = tuple(s.document.item_id for s in sources)
    service.evaluate(ids[0], ids[1:])
    row = acquisition_session.scalar(
        select(ModuleMessage).where(ModuleMessage.consumer == "comparison_selection_stage")
    )
    row.payload_json = {**row.payload_json, "ai_run_id": str(uuid4())}
    with pytest.raises(EditorialError, match="PAYLOAD_HASH_MISMATCH"):
        service.evaluate(ids[0], ids[1:])


def test_partial_failure_resumes_from_the_saved_plan(acquisition_session):
    service, sources, provider = prepared(acquisition_session, transient=True)
    ids = tuple(s.document.item_id for s in sources)
    with pytest.raises(EditorialError, match="COMPARISON_AI_OUTPUT_INVALID"):
        service.evaluate(ids[0], ids[1:])
    acquisition_session.commit()
    provider.transient = False
    audit = service.evaluate(ids[0], ids[1:])
    assert audit.outcome == "eligible"
    assert sum(c["model"] == "planner-test" for c in provider.calls) == 1
    assert len(provider.calls) == 7


def test_uncertain_source_plan_is_saved_and_deferred_without_candidate_calls(acquisition_session):
    service, sources, provider = prepared(acquisition_session)
    provider.intent = provider.intent.model_copy(
        update={"context_status": "needs_information", "missing_information": ("対象利用者",)}
    )
    ids = tuple(s.document.item_id for s in sources)
    audit = service.evaluate(ids[0], ids[1:])
    assert audit.outcome == "deferred"
    assert audit.reason_codes == ("COMPARISON_PLAN_INFORMATION_REQUIRED",)
    assert audit.plan.plan.missing_information == ("対象利用者",)
    assert len(provider.calls) == 1


def test_optional_information_does_not_defer_a_grounded_selection_task(acquisition_session):
    service, sources, provider = prepared(acquisition_session)
    provider.intent = provider.intent.model_copy(
        update={
            "context_status": "ready",
            "missing_information": ("任意の価格情報", "任意のAPI詳細"),
        }
    )
    ids = tuple(s.document.item_id for s in sources)
    audit = service.evaluate(ids[0], ids[1:])
    assert audit.outcome == "eligible"
    assert len(provider.calls) == 5
