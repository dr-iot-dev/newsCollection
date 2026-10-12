import pytest

from app.contracts.article_package_v1 import ArticlePackageV1
from app.core.article_tables import comparison_coverage, render_comparison_table
from app.core.editorial import EditorialError
from app.infrastructure.db.models import AiRun, Item
from app.modules.verification.service import verification_policy
from app.orchestration.editorial import EditorialService, checked_payload
from tests.unit.test_comparison_selection_orchestration import prepared


def selected_package(session):
    shadow, sources, provider = prepared(session)
    ids = tuple(s.document.item_id for s in sources)
    audit = shadow.evaluate(ids[0], ids[1:])
    settings = shadow.settings.model_copy(update={"comparison_selection_mode": "legacy"})
    editorial = EditorialService(session, settings)
    row = editorial.comparison(
        ids[0],
        previous_ids=(ids[1],),
        competitor_ids=(ids[2],),
        request_missing=False,
        selection_audit=audit,
    )
    return editorial, audit, checked_payload(row, ArticlePackageV1), provider


def test_explicit_selection_produces_concrete_table_and_distinct_verification_policy(
    acquisition_session,
):
    editorial, audit, package, _ = selected_package(acquisition_session)
    assert package.comparison_selection == audit
    table = render_comparison_table(package)
    assert "入力イベント" in table and "条件分岐" in table
    assert "技術・機能仕様" not in table
    assert comparison_coverage(package).valid
    assert verification_policy(package).endswith("+selection-v1")
    editorial.package(acquisition_session.get(Item, package.item_id))


def test_deferred_shadow_output_cannot_be_promoted_by_attaching_to_article(acquisition_session):
    shadow, sources, _ = prepared(acquisition_session, fail_review=True)
    ids = tuple(s.document.item_id for s in sources)
    audit = shadow.evaluate(ids[0], ids[1:])
    editorial = EditorialService(
        acquisition_session,
        shadow.settings.model_copy(update={"comparison_selection_mode": "legacy"}),
    )
    with pytest.raises(EditorialError, match="ARTICLE_SELECTION_NOT_APPROVED"):
        editorial.comparison(
            ids[0], competitor_ids=ids[1:], request_missing=False, selection_audit=audit
        )


def test_article_send_gate_rechecks_the_actual_independent_model_record(acquisition_session):
    editorial, audit, package, _ = selected_package(acquisition_session)
    independent = acquisition_session.get(AiRun, audit.independent_ai_run_id)
    independent.model = acquisition_session.get(AiRun, audit.plan.ai_run_id).model
    acquisition_session.flush()
    with pytest.raises(EditorialError, match="ARTICLE_SELECTION_AI_RECORD_INVALID"):
        editorial.package(acquisition_session.get(Item, package.item_id))


def test_source_number_order_is_bound_to_selected_products(acquisition_session):
    _, _, package, _ = selected_package(acquisition_session)
    tampered = package.model_copy(
        update={"source_references": tuple(reversed(package.source_references))}
    )
    with pytest.raises(EditorialError, match="ARTICLE_SELECTION_SOURCE_MISMATCH"):
        render_comparison_table(tampered)


def test_editorial_intent_change_creates_new_plan_and_is_cached_without_erasing_history(
    acquisition_session,
):
    shadow, sources, provider = prepared(acquisition_session)
    ids = tuple(s.document.item_id for s in sources)
    first = shadow.evaluate(
        ids[0], ids[1:], editorial_intent="現場データから業務を実行する方法を選ぶ"
    )
    repeat = shadow.evaluate(
        ids[0], ids[1:], editorial_intent="現場データから業務を実行する方法を選ぶ"
    )
    assert repeat == first and len(provider.calls) == 5
    second = shadow.evaluate(
        ids[0], ids[1:], editorial_intent="現場データを業務アクションへ接続する方法を選ぶ"
    )
    assert first.plan.plan_id != second.plan.plan_id
    assert second.plan.revision == first.plan.revision + 1
    assert second.plan.editorial_intent
    assert len(provider.calls) == 10
