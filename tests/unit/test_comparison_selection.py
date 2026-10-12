from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.comparison_selection_v1 import (
    INDEPENDENT_CHECKS,
    CandidateEvaluationV1,
    CandidateSuitabilityV1,
    ComparisonCellV1,
    ComparisonPlanOutputV1,
    ComparisonQuestionV1,
    ComparisonSuitabilityCheckV1,
    ComparisonSuitabilityOutputV1,
    GroundedJudgmentV1,
    GroundingV1,
    ProductDocumentV1,
    SourceExclusionBaselineV1,
    SourceExclusionEntryV1,
)
from app.contracts.evidence_v1 import EvidencePackageV1
from app.contracts.facts_v1 import VerifiedFactV1
from app.core.comparison_selection import (
    GroundedSource,
    choose_group,
    excluded,
    group_issues,
    primary_product,
    render_selection_table,
    validate_anchor,
    validate_candidate,
    validate_independent,
    validate_plan,
)
from app.core.editorial import EditorialError


def source(name="Workflow-A", company="Vendor-A", condition=None):
    item_id = uuid4()
    values = [
        ("organization", company),
        ("product", name),
        ("hardware_spec", "イベント入力、条件分岐、通知アクション"),
    ]
    body = "\n".join(v + (" " + condition if condition else "") for _, v in values)
    facts, anchors = [], {}
    offset = 0
    for kind, value in values:
        quote = value + (" " + condition if condition else "")
        fact = VerifiedFactV1(
            fact_id=uuid4(),
            evidence_id=uuid4(),
            fact_type=kind,
            subject=value if kind != "hardware_spec" else "発表内容",
            predicate=kind,
            value=value,
            conditions=condition if kind == "hardware_spec" else None,
        )
        anchor = GroundingV1(
            item_id=item_id,
            fact_id=fact.fact_id,
            evidence_id=fact.evidence_id,
            start=offset,
            end=offset + len(quote),
            quote=quote,
        )
        facts.append(fact)
        anchors[fact.fact_id] = anchor
        offset += len(quote) + 1
    return GroundedSource(
        ProductDocumentV1(
            item_id=item_id,
            item_version=1,
            url=f"https://example.test/{item_id}",
            extraction_hash="sha256:" + "0" * 64,
            evidence_hash="sha256:" + "1" * 64,
            body_hash=str(item_id),
            announcement_key=str(item_id),
            role="announcement",
        ),
        body,
        EvidencePackageV1(
            item_id=item_id,
            canonical_url=f"https://example.test/{item_id}",
            title=name,
            language="ja",
            facts=(),
            verified_facts=tuple(facts),
            quality_score=1,
        ),
        anchors,
    )


def judgment(source, text):
    return GroundedJudgmentV1(text=text, evidence=(list(source.anchors.values())[-1],))


def plan(source):
    product = primary_product(source)
    return ComparisonPlanOutputV1(
        product=GroundedJudgmentV1(text=product.name, evidence=(product.identity,)),
        product_kind=judgment(source, "ワークフロー基盤"),
        role=judgment(source, "業務実行"),
        audience=judgment(source, "運用者"),
        environment=judgment(source, "現場"),
        purpose=judgment(source, "イベントを条件判定して通知する"),
        selection_question="現場イベントから業務処理を実行する基盤を選ぶ",
        eligible_roles=("ワークフロー基盤",),
        excluded_roles=("ルータ監視", "換気制御"),
        questions=tuple(
            ComparisonQuestionV1(
                key=key,
                label=label,
                question=label + "は何か",
                required=True,
                answer_format="種類",
                applicability="全製品",
                evidence_requirement="原文",
            )
            for key, label in (
                ("input", "入力イベント"),
                ("branch", "条件分岐"),
                ("action", "実行アクション"),
            )
        ),
        search_queries=("現場イベント ワークフロー 条件分岐 通知",),
        context_status="ready",
        missing_information=(),
    )


def evaluation(source, plan, score=50):
    anchor = list(source.anchors.values())[-1]
    return CandidateEvaluationV1(
        plan_id=uuid4(),
        input_hash="sha256:" + "2" * 64,
        product=primary_product(source),
        ai_run_id=uuid4(),
        evaluation=CandidateSuitabilityV1(
            decision="eligible",
            role_fit="pass",
            purpose_fit="pass",
            audience_fit="pass",
            reason=GroundedJudgmentV1(
                text=primary_product(source).name + "は同じ条件判定と業務実行の選択肢",
                evidence=(primary_product(source).identity, anchor),
            ),
            score=score,
            cells=tuple(
                ComparisonCellV1(
                    question_key=q.key,
                    status="documented",
                    answer="通知",
                    evidence=(anchor,),
                    conditions=(),
                    plan=None,
                    version=None,
                    region=None,
                    as_of=None,
                )
                for q in plan.questions
            ),
            missing_question_keys=(),
            uncertainties=(),
        ),
    )


def test_plan_and_cells_have_real_fact_and_quote_grounding():
    target = source()
    intent = plan(target)
    validate_plan(intent, target)
    result = evaluation(target, intent)
    validate_candidate(result.evaluation, intent, result.product, {target.document.item_id: target})


@pytest.mark.parametrize(
    "field,value",
    [
        ("fact_id", uuid4()),
        ("evidence_id", uuid4()),
        ("item_id", uuid4()),
        ("start", 1),
        ("end", 9999),
        ("quote", "invented capability"),
    ],
)
def test_invented_or_moved_grounding_is_rejected(field, value):
    target = source()
    anchor = list(target.anchors.values())[-1].model_copy(update={field: value})
    with pytest.raises(EditorialError, match="COMPARISON_GROUNDING_INVALID"):
        validate_anchor(anchor, {target.document.item_id: target})


@pytest.mark.parametrize(
    "role,purpose,audience",
    [
        ("fail", "pass", "pass"),
        ("unknown", "pass", "pass"),
        ("pass", "fail", "pass"),
        ("pass", "unknown", "pass"),
        ("pass", "pass", "fail"),
        ("pass", "pass", "unknown"),
    ],
)
def test_high_score_cannot_override_role_task_or_audience_failure(role, purpose, audience):
    target = source()
    intent = plan(target)
    result = evaluation(target, intent, score=100)
    output = result.evaluation.model_copy(
        update={"role_fit": role, "purpose_fit": purpose, "audience_fit": audience}
    )
    with pytest.raises(EditorialError, match="COMPARISON_REQUIRED_CONDITION_FAILED"):
        validate_candidate(output, intent, result.product, {target.document.item_id: target})


def test_different_answer_methods_can_both_be_eligible():
    a, b = source(), source("Workflow-B", "Vendor-B")
    intent = plan(a)
    left, right = evaluation(a, intent), evaluation(b, intent)
    right = right.model_copy(
        update={
            "evaluation": right.evaluation.model_copy(
                update={
                    "cells": tuple(
                        c.model_copy(update={"answer": "イベント駆動"})
                        for c in right.evaluation.cells
                    )
                }
            )
        }
    )
    sources = {s.document.item_id: s for s in (a, b)}
    for entry in (left, right):
        validate_candidate(entry.evaluation, intent, entry.product, sources)
    assert not group_issues(intent, (left, right), 2, 2)


def test_other_product_fact_is_rejected_even_if_present_in_the_input():
    a, b = source(), source("Workflow-B", "Vendor-B")
    intent = plan(a)
    entry = evaluation(a, intent)
    cells = list(entry.evaluation.cells)
    cells[0] = cells[0].model_copy(update={"evidence": (list(b.anchors.values())[-1],)})
    with pytest.raises(EditorialError, match="COMPARISON_OTHER_PRODUCT_GROUNDING"):
        validate_candidate(
            entry.evaluation.model_copy(update={"cells": tuple(cells)}),
            intent,
            entry.product,
            {s.document.item_id: s for s in (a, b)},
        )


@pytest.mark.parametrize("condition", ["上位プラン限定", "補助適用後", "提供予定", "国内のみ"])
def test_condition_cannot_be_removed_or_flattened(condition):
    target = source(condition=condition)
    intent = plan(target)
    entry = evaluation(target, intent)
    sources = {target.document.item_id: target}
    with pytest.raises(EditorialError, match="COMPARISON_CELL_CONDITION_LOST"):
        validate_candidate(entry.evaluation, intent, entry.product, sources)
    cells = tuple(c.model_copy(update={"conditions": (condition,)}) for c in entry.evaluation.cells)
    with pytest.raises(EditorialError, match="COMPARISON_CELL_CONDITION_STATUS_INVALID"):
        validate_candidate(
            entry.evaluation.model_copy(update={"cells": cells}), intent, entry.product, sources
        )
    cells = tuple(c.model_copy(update={"status": "conditional"}) for c in cells)
    validate_candidate(
        entry.evaluation.model_copy(update={"cells": cells}), intent, entry.product, sources
    )


def test_question_cannot_be_deleted_to_pass():
    target = source()
    intent = plan(target)
    entry = evaluation(target, intent)
    with pytest.raises(EditorialError, match="COMPARISON_QUESTION_SET_MISMATCH"):
        validate_candidate(
            entry.evaluation.model_copy(update={"cells": entry.evaluation.cells[1:]}),
            intent,
            entry.product,
            {target.document.item_id: target},
        )


def test_duplicate_questions_and_missing_independent_checks_are_schema_errors():
    target = source()
    intent = plan(target).model_dump()
    intent["questions"] = [intent["questions"][0]] * 3
    with pytest.raises(ValidationError):
        ComparisonPlanOutputV1.model_validate(intent)
    check = dict(key=INDEPENDENT_CHECKS[0], result="pass", reason="supported", fact_ids=[])
    with pytest.raises(ValidationError):
        ComparisonSuitabilityOutputV1(checks=[check] * 5, blocking_issues=())


@pytest.mark.parametrize("match", ["url", "body_hash", "announcement_key"])
def test_exclusions_cover_url_reprint_and_same_announcement(match):
    target = source()
    kwargs = {"url": "https://example.test/unrelated", match: getattr(target.document, match)}
    baseline = SourceExclusionBaselineV1(
        baseline_id=uuid4(),
        captured_at=datetime.now(UTC),
        scope="batch",
        entries=(SourceExclusionEntryV1(**kwargs, source="wordpress"),),
    )
    assert excluded(target, baseline)
    assert not excluded(source(), baseline)


@pytest.mark.parametrize(
    "scenario", ["valid", "role", "required", "duplicates", "reprint", "support"]
)
def test_joint_product_and_announcement_coverage(scenario):
    sources = [source(f"Workflow-{i}", f"Vendor-{i}") for i in range(3)]
    intent = plan(sources[0])
    group = [evaluation(s, intent) for s in sources]
    if scenario == "role":
        group[1] = group[1].model_copy(
            update={
                "evaluation": group[1].evaluation.model_copy(
                    update={"decision": "rejected", "role_fit": "fail"}
                )
            }
        )
    elif scenario == "required":
        cells = list(group[1].evaluation.cells)
        cells[0] = cells[0].model_copy(update={"status": "unknown", "evidence": ()})
        group[1] = group[1].model_copy(
            update={"evaluation": group[1].evaluation.model_copy(update={"cells": tuple(cells)})}
        )
    elif scenario == "duplicates":
        group[1] = group[1].model_copy(update={"product": group[0].product})
    elif scenario == "reprint":
        doc = (
            group[1]
            .product.documents[0]
            .model_copy(update={"body_hash": group[0].product.documents[0].body_hash})
        )
        group[1] = group[1].model_copy(
            update={"product": group[1].product.model_copy(update={"documents": (doc,)})}
        )
    elif scenario == "support":
        # Answers cite feature pages, leaving announcement votes absent.
        for i in (1, 2):
            doc = group[i].product.documents[0].model_copy(update={"role": "features"})
            group[i] = group[i].model_copy(
                update={"product": group[i].product.model_copy(update={"documents": (doc,)})}
            )
        # Keep the original announcement documents to retain the three-vote denominator.
        for i in (1, 2):
            doc = sources[i].document.model_copy(update={"item_id": uuid4()})
            group[i] = group[i].model_copy(
                update={
                    "product": group[i].product.model_copy(
                        update={"documents": (*group[i].product.documents, doc)}
                    )
                }
            )
    issues = group_issues(intent, group, 3, 3)
    assert bool(issues) == (scenario != "valid")
    if scenario == "support":
        assert "COMPARISON_ANNOUNCEMENT_MAJORITY_REQUIRED:input" in issues


def test_rerank_after_extraction_and_render_concrete_rows():
    sources = [source(f"Workflow-{i}", f"Vendor-{i}") for i in range(4)]
    intent = plan(sources[0])
    group = [evaluation(s, intent, score=20 + i * 20) for i, s in enumerate(sources)]
    selected = choose_group(intent, group[0], group[1:], 3, 3)
    assert selected == (group[0], group[3], group[2])
    table = render_selection_table(intent, selected)
    assert "入力イベント" in table and "条件分岐" in table and "技術・機能仕様" not in table
    assert all(s.product.documents[0].url in table for s in selected)


def test_independent_review_cannot_cite_a_nonexistent_fact():
    target = source()
    intent = plan(target)
    entry = evaluation(target, intent)
    report = ComparisonSuitabilityOutputV1(
        checks=tuple(
            ComparisonSuitabilityCheckV1(
                key=k, result="pass", reason="supported", fact_ids=(uuid4(),)
            )
            for k in INDEPENDENT_CHECKS
        ),
        blocking_issues=(),
    )
    with pytest.raises(EditorialError, match="COMPARISON_REVIEW_FACT_REFERENCE_INVALID"):
        validate_independent(report, (entry,), {target.document.item_id: target})


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan", "Enterprise"),
        ("version", "v5"),
        ("region", "Europe"),
        ("as_of", "2026-10-10"),
    ],
)
def test_qualifiers_must_have_source_grounding(field, value):
    target = source()
    intent = plan(target)
    entry = evaluation(target, intent)
    cells = tuple(c.model_copy(update={field: value}) for c in entry.evaluation.cells)
    with pytest.raises(EditorialError, match="COMPARISON_CELL_QUALIFIER_UNGROUNDED"):
        validate_candidate(
            entry.evaluation.model_copy(update={"cells": cells}),
            intent,
            entry.product,
            {target.document.item_id: target},
        )


def test_candidate_reason_cannot_name_the_target_instead_of_candidate():
    candidate = source("Workflow-Candidate", "Candidate Vendor")
    intent = plan(source("Workflow-Target", "Target Vendor"))
    entry = evaluation(candidate, intent)
    reason = entry.evaluation.reason.model_copy(
        update={"text": "Workflow-Targetは同じ条件判定と業務実行の選択肢"}
    )
    with pytest.raises(EditorialError, match="COMPARISON_REASON_PRODUCT_MISMATCH"):
        validate_candidate(
            entry.evaluation.model_copy(update={"reason": reason}),
            intent,
            entry.product,
            {candidate.document.item_id: candidate},
        )
