from dataclasses import replace
from math import nan
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.ai.provider import AIResponse
from app.ai.runner import AIRunner
from app.contracts.comparison_discovery_v2 import CHECKS, ComparisonDiscoveryRequestV2
from app.core.editorial import EditorialError, personal_data
from app.infrastructure.comparison_retrieval import (
    Embedding,
    cosine,
    rank_candidates,
    rank_seeded_groups,
    reciprocal_rank_fusion,
)
from app.infrastructure.db.models import (
    AiRun,
    ArticleDraft,
    ExtractionResult,
    Item,
    ModuleMessage,
    Publication,
)
from app.orchestration.comparison_discovery import ComparisonDiscoveryService
from tests.unit.test_comparison_selection_orchestration import prepared


class DiscoveryProvider:
    def __init__(
        self,
        original,
        fail_review=False,
        invalid_plan=False,
        two_hypotheses=False,
        fail_first_assessment=False,
        abstain=False,
        inline_refs=False,
        unsupported_number=False,
        profile_error=None,
        inventory_error=None,
    ):
        self.original = original
        self.calls = []
        self.fail_review = fail_review
        self.invalid_plan = invalid_plan
        self.two_hypotheses = two_hypotheses
        self.fail_first_assessment = fail_first_assessment
        self.abstain = abstain
        self.inline_refs = inline_refs
        self.unsupported_number = unsupported_number
        self.profile_error = profile_error
        self.inventory_error = inventory_error

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if "dimensions" in kwargs.get("schema", {}).get("properties", {}):
            dimensions = []
            for question in self.original.intent.questions:
                supports = []
                for source in self.original.sources:
                    own = self.original.generate(
                        model="assessor-test",
                        data={"source": {"document": source.document.model_dump(mode="json")}},
                    ).output
                    supports.append(
                        {
                            "item_id": str(source.document.item_id),
                            "cell": next(
                                c for c in own["cells"] if c["question_key"] == question.key
                            ),
                        }
                    )
                q = question.model_dump(mode="json")
                q["required"] = False
                dimensions.append({"question": q, "supports": supports})
            if self.inventory_error == "foreign":
                dimensions[0]["supports"][0]["cell"]["fact_ids"] = dimensions[0]["supports"][1][
                    "cell"
                ]["fact_ids"]
            elif self.inventory_error == "number":
                dimensions[0]["supports"][0]["cell"]["answer"] += "987654321件"
            elif self.inventory_error == "multiple_numbers":
                dimensions[0]["supports"][0]["cell"]["answer"] += "987654321件"
                dimensions[0]["supports"][2]["cell"]["answer"] += "987654321件"
            elif self.inventory_error == "duplicate":
                dimensions[0]["supports"][1] = dimensions[0]["supports"][0]
            elif self.inventory_error == "unknown_with_refs":
                dimensions[0]["supports"][0]["cell"]["status"] = "unknown"
            return AIResponse({"dimensions": dimensions, "limitations": []}, "fixture", 100, 20, 1)
        if "catalog" in kwargs["data"] and "profiles" in kwargs.get("schema", {}).get(
            "properties", {}
        ):
            profiles = []
            for source in self.original.sources:
                refs = [str(f.fact_id) for f in source.evidence.verified_facts]
                name = next(
                    f.value for f in source.evidence.verified_facts if f.fact_type == "product"
                )
                profiles.append(
                    {
                        "item_id": str(source.document.item_id),
                        "role": {"text": name + "を自ら操作する製品", "fact_ids": refs},
                        "purpose": {"text": "記載された機能を利用する", "fact_ids": refs},
                        "targets": None,
                        "method": None,
                        "results": None,
                        "material_missing_information": ["現行提供状況は未確認"],
                    }
                )
            if self.profile_error == "foreign":
                profiles[0]["purpose"]["fact_ids"] = profiles[1]["purpose"]["fact_ids"]
            elif self.profile_error == "number":
                profiles[0]["purpose"]["text"] += "999999件の検出"
            elif self.profile_error == "duplicate":
                profiles[1] = profiles[0]
            return AIResponse({"profiles": profiles}, "fixture", 100, 20, 1)
        if "catalog" in kwargs["data"]:
            sources = self.original.sources
            output = {
                "groups": []
                if self.abstain
                else [
                    {
                        "item_ids": [str(s.document.item_id) for s in sources],
                        "selection_task": {
                            "text": self.original.intent.purpose.text,
                            "fact_ids": [
                                str(a.fact_id) for a in self.original.intent.purpose.evidence
                            ],
                        },
                        "product_reasons": [
                            {
                                "item_id": str(s.document.item_id),
                                "judgment": {
                                    "text": next(
                                        f.value
                                        for f in s.evidence.verified_facts
                                        if f.fact_type == "product"
                                    )
                                    + "を比較する",
                                    "fact_ids": [str(f.fact_id) for f in s.evidence.verified_facts],
                                },
                            }
                            for s in sources
                        ],
                    }
                ],
                "unsuitable_reasons": ["用途に合う代替案が不足"] if self.abstain else [],
            }
            if self.invalid_plan:
                output["groups"][0]["item_ids"][0] = str(uuid4())
            return AIResponse(output, "fixture", 100, 20, 1)
        if kwargs["model"] == "planner-test":
            if self.abstain:
                return AIResponse(
                    {
                        "hypotheses": [],
                        "unsuitable_reasons": [
                            "対象用途に重要な三つの主要項目を全製品で確認できない"
                        ],
                    },
                    "fixture",
                    100,
                    20,
                    1,
                )
            intent = self.original.intent
            sources = self.original.sources
            output = {
                "hypotheses": [
                    {
                        "purpose": {
                            "text": intent.purpose.text,
                            "fact_ids": [str(a.fact_id) for a in intent.purpose.evidence],
                        },
                        "audience": {
                            "text": intent.audience.text,
                            "fact_ids": [str(a.fact_id) for a in intent.audience.evidence],
                        },
                        "selection_question": intent.selection_question,
                        "eligible_roles": intent.eligible_roles,
                        "excluded_roles": intent.excluded_roles,
                        "questions": [q.model_dump(mode="json") for q in intent.questions],
                        "product_reasons": [
                            {
                                "item_id": str(s.document.item_id),
                                "judgment": {
                                    "text": next(
                                        f.value
                                        for f in s.evidence.verified_facts
                                        if f.fact_type == "product"
                                    )
                                    + "を比較に含める",
                                    "fact_ids": [
                                        str(f.fact_id)
                                        for f in s.evidence.verified_facts
                                        if f.fact_type == "product"
                                    ],
                                },
                            }
                            for s in sources
                        ],
                        "meaningful_differences": ["検知結果の通知方法"],
                        "material_missing_information": [],
                    }
                ],
                "unsuitable_reasons": [],
            }
            support = []
            for source in sources:
                own = self.original.generate(
                    model="assessor-test",
                    data={"source": {"document": source.document.model_dump(mode="json")}},
                ).output
                support.extend(
                    {"item_id": str(source.document.item_id), "cell": c} for c in own["cells"]
                )
            output["hypotheses"][0]["question_support"] = support
            if self.two_hypotheses:
                import copy

                second = copy.deepcopy(output["hypotheses"][0])
                second["selection_question"] = "通知を利用する別の選択用途を検討する"
                output["hypotheses"].append(second)
            if self.invalid_plan:
                output["hypotheses"][0]["purpose"]["fact_ids"] = [str(uuid4())]
            if self.inline_refs:
                for reason in output["hypotheses"][0]["product_reasons"]:
                    reason["judgment"]["text"] += (
                        "\uff08" + reason["judgment"]["fact_ids"][0] + "\uff09"
                    )
            if self.unsupported_number:
                output["hypotheses"][0]["purpose"]["text"] += "999999件の検出"
        elif kwargs["model"] == "assessor-test":
            if (
                self.fail_first_assessment
                and kwargs["data"]["selection_task"] == self.original.intent.selection_question
            ):
                raise EditorialError("DISCOVERY_CELL_UNSUPPORTED_NUMBER")
            return self.original.generate(**kwargs)
        else:
            output = {
                "checks": [
                    {
                        "key": k,
                        "result": "fail"
                        if self.fail_review and k == "material_omissions"
                        else "pass",
                        "reason": "Grounded editorial test",
                        "fact_ids": [
                            str(self.original.sources[0].evidence.verified_facts[0].fact_id)
                        ],
                    }
                    for k in CHECKS
                ],
                "blocking_issues": ["Critical gap"] if self.fail_review else [],
            }
        return AIResponse(output, "fixture", 100, 20, 1)


def setup(session, **kwargs):
    old, sources, original = prepared(session)
    provider = DiscoveryProvider(original, **kwargs)
    service = ComparisonDiscoveryService(
        session, old.settings, AIRunner(session, old.settings, provider), checkpoint=True
    )
    request = ComparisonDiscoveryRequestV2(
        seed_item_id=sources[0].document.item_id,
        candidate_item_ids=tuple(s.document.item_id for s in sources[1:]),
        maximum_groups=1,
    )
    return service, request, sources, provider


def test_joint_exploration_is_grounded_resumable_and_never_promotes(acquisition_session):
    service, request, sources, provider = setup(acquisition_session)
    states = {
        s.document.item_id: acquisition_session.get(Item, s.document.item_id).status
        for s in sources
    }
    first = service.discover(request)
    assert first.outcome == "eligible" and first.frozen_hash and first.api_calls_used == 5
    assert len(provider.calls) == 5
    planning = provider.calls[0]["data"]
    assert len(planning["sources"]) == 3 and "plan" not in planning
    again = service.discover(request)
    assert again.frozen_hash == first.frozen_hash and len(provider.calls) == 5
    assert again.api_calls_used == 5
    assert acquisition_session.scalar(select(ArticleDraft)) is None
    assert acquisition_session.scalar(select(Publication)) is None
    assert (
        acquisition_session.scalar(
            select(ModuleMessage).where(ModuleMessage.consumer == "comparison_selection_audit")
        )
        is None
    )
    assert states == {key: acquisition_session.get(Item, key).status for key in states}
    assert all(
        c.text
        == sources[next(i for i, s in enumerate(sources) if s.document.item_id == c.item_id)].body[
            c.start : c.end
        ]
        for c in first.contexts
    )


def test_major_omissions_cannot_be_overridden_by_scores(acquisition_session):
    service, request, _, _ = setup(acquisition_session, fail_review=True)
    audit = service.discover(request)
    assert audit.outcome == "deferred" and audit.frozen_hash is None
    assert len(audit.groups) == 1 and not audit.groups[0].accepted
    assert len(audit.groups[0].independent.checks) == 6


@pytest.mark.parametrize("unsupported", [False, True])
def test_inline_fact_uuid_normalization_preserves_real_number_guard(
    acquisition_session, unsupported
):
    service, request, _sources, _provider = setup(
        acquisition_session, inline_refs=True, unsupported_number=unsupported
    )
    audit = service.discover(request)
    assert audit.outcome == ("deferred" if unsupported else "eligible")
    if not unsupported:
        for reason in audit.groups[0].plan.hypothesis.product_reasons:
            assert str(reason.judgment.fact_ids[0]) not in reason.judgment.text
            assert reason.judgment.fact_ids
        assert service.discover(request).frozen_hash == audit.frozen_hash


def test_inline_unknown_uuid_is_not_silently_deleted():
    from app.contracts.comparison_selection_ai_v1 import GroundedJudgmentRefV1
    from app.core.comparison_discovery import normalize_judgment_references

    key = uuid4()
    value = GroundedJudgmentRefV1(text="未登録根拠 " + str(uuid4()), fact_ids=(key,))
    with pytest.raises(EditorialError, match="DISCOVERY_FACT_REFERENCE_INVALID"):
        normalize_judgment_references(value, {key})


def test_semantic_catalog_selection_is_a_hint_and_reuses_completed_stages(acquisition_session):
    service, request, sources, provider = setup(acquisition_session)
    request = request.model_copy(update={"group_selection": "semantic"})
    audit = service.discover(request)
    assert audit.outcome == "eligible" and audit.api_calls_used == 6
    assert len(provider.calls[0]["data"]["catalog"]) == 3
    assert audit.semantic_group_selection_ai_run_id
    assert audit.group_ranking[0].method == "semantic_group_proposal"
    assert set(audit.retrieval.detailed_item_ids) == {s.document.item_id for s in sources}
    assert "tentative_group_hint" in provider.calls[1]["data"]
    assert service.discover(request).frozen_hash == audit.frozen_hash
    assert len(provider.calls) == 6
    assert acquisition_session.scalar(select(ArticleDraft)) is None
    assert acquisition_session.scalar(select(Publication)) is None


def test_independent_review_excludes_superseded_planning_data(acquisition_session, monkeypatch):
    service, request, sources, provider = setup(acquisition_session)
    request = request.model_copy(update={"evidence_first": True, "group_selection": "semantic"})
    evaluate = service.evaluate_hypothesis

    def with_obsolete_proposal(frozen_plan, own_sources, data, unsuitable_reasons):
        return evaluate(
            frozen_plan,
            own_sources,
            {**data, "superseded_proposal": {"answer": "Unapproved obsolete price 987654321"}},
            unsuitable_reasons,
        )

    monkeypatch.setattr(service, "evaluate_hypothesis", with_obsolete_proposal)
    audit = service.discover(request)
    assert audit.outcome == "eligible"
    planning = next(
        call["data"] for call in provider.calls if "hypotheses" in call["schema"]["properties"]
    )
    assert "tentative_evidence_inventory" in planning and "tentative_group_hint" in planning
    review = next(call["data"] for call in provider.calls if call["model"] == "independent-test")
    assert set(review) == {"sources", "editorial_intent", "group", "policy"}
    assert review["group"]["plan"]["hypothesis"] == audit.groups[0].plan.hypothesis.model_dump(
        mode="json"
    )
    assert {s["document"]["item_id"] for s in review["sources"]} == {
        str(s.document.item_id) for s in sources
    }
    assert service.discover(request).frozen_hash == audit.frozen_hash
    assert len(provider.calls) == 7


def test_frozen_group_requires_current_review_policy(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    audit = service.discover(request)
    group = service.validate_frozen(audit)
    review = acquisition_session.get(AiRun, group.independent_ai_run_id)
    assert review.prompt_version == "discovery_review-v2"
    review.prompt_version = "discovery_review-v1"
    acquisition_session.flush()
    with pytest.raises(EditorialError, match="DISCOVERY_FROZEN_REVIEW_POLICY_CHANGED"):
        service.validate_frozen(audit)
    assert len(provider.calls) == 5
    assert acquisition_session.scalar(select(ArticleDraft)) is None
    assert acquisition_session.scalar(select(Publication)) is None


def test_evidence_inventory_is_cached_and_does_not_approve_article(acquisition_session):
    service, request, sources, provider = setup(acquisition_session, fail_review=True)
    request = request.model_copy(update={"evidence_first": True})
    audit = service.discover(request)
    assert audit.outcome == "deferred" and audit.api_calls_used == 6
    entry = audit.planning[0]
    assert entry.evidence_inventory and entry.evidence_inventory_ai_run_id
    assert all(not d.question.required for d in entry.evidence_inventory.dimensions)
    assert "tentative_evidence_inventory" in provider.calls[1]["data"]
    assert audit.groups[0].independent and not audit.groups[0].accepted
    assert service.discover(request).api_calls_used == 6
    assert len(provider.calls) == 6
    assert acquisition_session.scalar(select(ArticleDraft)) is None
    assert acquisition_session.scalar(select(Publication)) is None
    allowed = {str(fid) for s in sources for fid in s.anchors}
    assert (
        set(
            provider.calls[0]["schema"]["$defs"]["ComparisonCellRefV1"]["properties"]["fact_ids"][
                "items"
            ]["enum"]
        )
        == allowed
    )


@pytest.mark.parametrize("error", ["foreign", "number", "duplicate", "unknown_with_refs"])
def test_invalid_inventory_stops_before_plan_without_fallback(acquisition_session, error):
    service, request, _, provider = setup(acquisition_session, inventory_error=error)
    request = request.model_copy(update={"evidence_first": True})
    audit = service.discover(request)
    assert audit.outcome == "deferred" and audit.api_calls_used == 2
    assert not audit.groups and audit.planning[0].error_code == "DISCOVERY_AI_OUTPUT_INVALID"
    assert audit.planning[0].evidence_inventory is None
    assert service.discover(request).api_calls_used == 2 and len(provider.calls) == 2


def test_inventory_budget_limit_keeps_completed_evidence_without_planning(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    request = request.model_copy(update={"evidence_first": True, "maximum_api_calls": 1})
    audit = service.discover(request)
    assert audit.outcome == "deferred" and audit.api_calls_used == 1
    assert audit.planning[0].evidence_inventory and audit.planning[0].evidence_inventory_ai_run_id
    assert audit.planning[0].error_code == "DISCOVERY_API_BUDGET_EXHAUSTED"
    assert service.discover(request).api_calls_used == 1 and len(provider.calls) == 1


def test_semantic_group_output_uses_homogeneous_provider_array_schema():
    from app.ai.provider import strict_schema
    from app.contracts.comparison_discovery_v2 import DiscoveryGroupSelectionV2

    schema = strict_schema(DiscoveryGroupSelectionV2.model_json_schema())
    ids = schema["$defs"]["DiscoveryGroupHintV2"]["properties"]["item_ids"]
    assert ids["items"]["type"] == "string"
    assert ids["minItems"] == ids["maxItems"] == 3
    assert "prefixItems" not in ids


def test_semantic_profiles_are_cached_hints_and_never_bypass_review(acquisition_session):
    service, request, sources, provider = setup(acquisition_session, fail_review=True)
    request = request.model_copy(update={"group_selection": "semantic", "semantic_profiles": True})
    audit = service.discover(request)
    assert audit.outcome == "deferred" and audit.api_calls_used == 7
    assert audit.semantic_profiles_ai_run_id
    assert all(
        p.semantic and p.representation == "grounded_semantic_and_keywords" for p in audit.profiles
    )
    assert all(p.semantic.targets is None for p in audit.profiles)
    assert "semantic_profile" in provider.calls[1]["data"]["catalog"][0]
    assert audit.groups[0].independent and not audit.groups[0].accepted
    assert (
        service.discover(request).semantic_profiles_ai_run_id == audit.semantic_profiles_ai_run_id
    )
    assert len(provider.calls) == 7
    assert {p.semantic.item_id for p in audit.profiles} == {s.document.item_id for s in sources}


@pytest.mark.parametrize("error", ["foreign", "number", "duplicate"])
def test_invalid_semantic_profiles_stop_without_group_fallback(acquisition_session, error):
    service, request, _, provider = setup(acquisition_session, profile_error=error)
    request = request.model_copy(update={"group_selection": "semantic", "semantic_profiles": True})
    audit = service.discover(request)
    assert audit.outcome == "deferred" and not audit.group_ranking and not audit.planning
    assert audit.api_calls_used == 2 and len(provider.calls) == 2
    assert audit.semantic_profiles_ai_run_id is None
    assert service.discover(request).api_calls_used == 2 and len(provider.calls) == 2


def test_profile_budget_reservation_precedes_group_proposal(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    request = request.model_copy(
        update={
            "group_selection": "semantic",
            "semantic_profiles": True,
            "maximum_api_calls": 1,
            "budget_id": uuid4(),
        }
    )
    audit = service.discover(request)
    assert audit.api_calls_used == 1 and len(provider.calls) == 1
    assert audit.semantic_profiles_ai_run_id and audit.semantic_group_selection is None
    assert "DISCOVERY_API_BUDGET_EXHAUSTED" in audit.reason_codes
    assert acquisition_session.scalar(select(ArticleDraft)) is None
    assert acquisition_session.scalar(select(Publication)) is None


@pytest.mark.parametrize("mode,expected_calls", [("keyword_mmr", 0), ("semantic", 2)])
def test_round_group_exclusion_does_not_repeat_known_triple(
    acquisition_session, mode, expected_calls
):
    service, request, sources, provider = setup(acquisition_session)
    request = request.model_copy(
        update={
            "group_selection": mode,
            "excluded_group_item_ids": (tuple(s.document.item_id for s in sources),),
        }
    )
    audit = service.discover(request)
    assert audit.outcome == "deferred" and not audit.planning and not audit.group_ranking
    assert audit.api_calls_used == expected_calls and len(provider.calls) == expected_calls


def test_profile_mode_and_round_exclusions_validate_request():
    from pydantic import ValidationError

    seed, a, b = uuid4(), uuid4(), uuid4()
    with pytest.raises(ValidationError):
        ComparisonDiscoveryRequestV2(seed_item_id=seed, semantic_profiles=True)
    with pytest.raises(ValidationError):
        ComparisonDiscoveryRequestV2(seed_item_id=seed, excluded_group_item_ids=((seed, a, a),))
    with pytest.raises(ValidationError):
        ComparisonDiscoveryRequestV2(
            seed_item_id=seed, excluded_group_item_ids=((seed, a, b), (b, a, seed))
        )


@pytest.mark.parametrize("failure", ["abstain", "invalid_plan", "fail_review"])
def test_semantic_selection_never_falls_back_or_bypasses_quality(acquisition_session, failure):
    service, request, _, provider = setup(acquisition_session, **{failure: True})
    request = request.model_copy(update={"group_selection": "semantic"})
    audit = service.discover(request)
    assert audit.outcome == "deferred" and audit.frozen_hash is None
    if failure == "fail_review":
        assert len(provider.calls) == 6 and audit.groups[0].independent
    else:
        assert len(provider.calls) == (1 if failure == "abstain" else 2)
        assert not audit.group_ranking and not audit.planning
    assert service.discover(request).api_calls_used == audit.api_calls_used


@pytest.mark.parametrize(
    "corruption,code",
    [
        ("foreign", "DISCOVERY_OTHER_PRODUCT_GROUNDING"),
        ("identity_only", "DISCOVERY_REASON_FUNCTION_REQUIRED"),
        ("duplicate", "DISCOVERY_PRODUCT_SET_MISMATCH"),
        ("number", "DISCOVERY_UNSUPPORTED_NUMBER"),
    ],
)
def test_semantic_group_guards_preserve_source_ownership(acquisition_session, corruption, code):
    from app.contracts.comparison_discovery_v2 import DiscoveryGroupSelectionV2
    from app.core.comparison_discovery import validate_group_selection
    from app.core.comparison_selection import primary_product

    _service, request, sources, provider = setup(acquisition_session)
    raw = provider.generate(model="planner-test", data={"catalog": []}).output
    group = raw["groups"][0]
    if corruption == "foreign":
        group["product_reasons"][0]["judgment"]["fact_ids"].append(
            str(next(iter(sources[1].anchors)))
        )
    elif corruption == "identity_only":
        group["product_reasons"][0]["judgment"]["fact_ids"] = [
            str(primary_product(sources[0]).identity.fact_id)
        ]
    elif corruption == "duplicate":
        raw["groups"].append(group)
        request = request.model_copy(update={"maximum_groups": 2})
    else:
        group["selection_task"]["text"] += "999999件の検出"
    with pytest.raises(EditorialError, match=code):
        validate_group_selection(
            DiscoveryGroupSelectionV2.model_validate(raw),
            {s.document.item_id: s for s in sources},
            request,
        )


def test_semantic_group_can_select_beyond_keyword_detailed_pool(acquisition_session, monkeypatch):
    from tests.unit.test_comparison_selection import source

    service, request, sources, _provider = setup(acquisition_session)
    extra = source("Other-Product")
    all_sources = {s.document.item_id: s for s in (*sources, extra)}
    # Force a keyword ordering that puts a selected source outside the first three.
    ranked = [
        sources[0].document.item_id,
        extra.document.item_id,
        sources[1].document.item_id,
        sources[2].document.item_id,
    ]
    monkeypatch.setattr(service, "source", lambda key: all_sources[key])
    monkeypatch.setattr(
        "app.orchestration.comparison_discovery.rank_candidates",
        lambda *_args: (ranked, {key: 0.5 for key in ranked}),
    )
    request = request.model_copy(
        update={
            "group_selection": "semantic",
            "detailed_pool_size": 3,
            "candidate_item_ids": tuple(ranked[1:]),
        }
    )
    audit = service.discover(request)
    assert audit.outcome == "eligible"
    assert sources[2].document.item_id in audit.retrieval.detailed_item_ids
    assert extra.document.item_id not in audit.retrieval.detailed_item_ids


def test_semantic_selected_union_cannot_exceed_detailed_pool(acquisition_session):
    from app.contracts.comparison_discovery_v2 import DiscoveryGroupSelectionV2
    from app.core.comparison_discovery import validate_group_selection
    from app.core.comparison_selection import primary_product
    from tests.unit.test_comparison_selection import source

    _service, request, sources, provider = setup(acquisition_session)
    raw = provider.generate(model="planner-test", data={"catalog": []}).output
    extra = source("Other-Product")
    first = raw["groups"][0]
    import copy

    second = copy.deepcopy(first)
    second["item_ids"][2] = str(extra.document.item_id)
    second["product_reasons"][2] = {
        "item_id": str(extra.document.item_id),
        "judgment": {
            "text": primary_product(extra).name + "を比較する",
            "fact_ids": [str(f.fact_id) for f in extra.evidence.verified_facts],
        },
    }
    raw["groups"].append(second)
    request = request.model_copy(update={"maximum_groups": 2, "detailed_pool_size": 3})
    with pytest.raises(EditorialError, match="DISCOVERY_HYPOTHESIS_BUDGET_EXCEEDED"):
        validate_group_selection(
            DiscoveryGroupSelectionV2.model_validate(raw),
            {s.document.item_id: s for s in (*sources, extra)},
            request,
        )


def test_missing_major_answer_cannot_be_overridden_by_other_products(acquisition_session):
    from app.core.comparison_discovery import group_issues

    service, request, _, _ = setup(acquisition_session)
    group = service.discover(request).groups[0]
    entry = group.evaluations[0]
    cell = entry.evaluation.cells[0]
    missing_cell = cell.model_copy(update={"status": "unknown", "evidence": ()})
    missing_entry = entry.model_copy(
        update={
            "evaluation": entry.evaluation.model_copy(
                update={"cells": (missing_cell, *entry.evaluation.cells[1:])}
            )
        }
    )
    changed = group.model_copy(update={"evaluations": (missing_entry, *group.evaluations[1:])})
    assert "DISCOVERY_MAJOR_QUESTION_MISSING:" + cell.question_key in group_issues(changed)


def test_foreign_product_fact_cannot_be_used_in_a_cell(acquisition_session):
    from app.contracts.comparison_selection_ai_v1 import CandidateSuitabilityAIOutputV1

    service, request, sources, provider = setup(acquisition_session)
    service.discover(request)
    call = next(c for c in provider.calls if c["model"] == "assessor-test")
    output = provider.original.generate(**call).output
    own_id = call["data"]["source"]["document"]["item_id"]
    own = next(s for s in sources if str(s.document.item_id) == own_id)
    foreign = next(s for s in sources if s != own)
    output["cells"][0]["fact_ids"] = [str(next(iter(foreign.anchors)))]
    value = CandidateSuitabilityAIOutputV1.model_validate(output)
    with pytest.raises(EditorialError, match="COMPARISON_GROUNDING_INVALID"):
        service.validate_assessment(value, provider.original.intent.questions, own)


def test_invalid_plan_attempts_count_and_cannot_repeat_until_pass(acquisition_session):
    service, request, _, provider = setup(acquisition_session, invalid_plan=True)
    first = service.discover(request)
    assert first.outcome == "deferred" and first.api_calls_used == 2
    provider.invalid_plan = False
    again = service.discover(request)
    assert again.outcome == "deferred" and again.api_calls_used == 2
    assert len(provider.calls) == 2
    assert "DISCOVERY_STAGE_PREVIOUSLY_INCOMPLETE" in again.reason_codes


def test_failed_hypothesis_is_saved_and_alternative_is_still_evaluated(acquisition_session):
    service, request, _, provider = setup(
        acquisition_session, two_hypotheses=True, fail_first_assessment=True
    )
    audit = service.discover(request)
    assert len(audit.groups) == 2 and audit.outcome == "eligible"
    assert audit.groups[0].issues == ("DISCOVERY_AI_OUTPUT_INVALID",)
    assert not audit.groups[0].accepted and audit.groups[1].accepted
    assert audit.api_calls_used == 7 and len(provider.calls) == 7
    repeat = service.discover(request)
    assert repeat.outcome == "eligible" and repeat.api_calls_used == 7
    assert len(provider.calls) == 7


def test_explained_abstention_is_saved_without_forcing_invalid_hypothesis(acquisition_session):
    from pydantic import ValidationError

    from app.contracts.comparison_discovery_v2 import ComparisonGroupProposalV2

    service, request, _, provider = setup(acquisition_session, abstain=True)
    audit = service.discover(request)
    assert audit.outcome == "deferred" and not audit.groups
    assert audit.api_calls_used == 1 and len(provider.calls) == 1
    assert audit.planning[0].proposal.unsuitable_reasons
    assert not audit.planning[0].error_code
    assert "DISCOVERY_NO_USEFUL_HYPOTHESIS" in audit.reason_codes
    assert "DISCOVERY_AI_OUTPUT_INVALID" not in audit.reason_codes
    assert service.discover(request).api_calls_used == 1 and len(provider.calls) == 1
    with pytest.raises(ValidationError):
        ComparisonGroupProposalV2(hypotheses=(), unsuitable_reasons=())


def test_discovery_diagnostics_keep_known_error_without_raw_data():
    from app.ai.diagnostics import validation_diagnostics
    from app.contracts.comparison_selection_ai_v1 import CandidateSuitabilityAIOutputV1

    errors = validation_diagnostics(
        EditorialError(
            "DISCOVERY_CELL_CONDITION_LOST",
            path=("cells", 0, "conditions", "sk-private-do-not-log"),
        ),
        CandidateSuitabilityAIOutputV1,
        1,
    )
    assert errors[0]["code"] == "DISCOVERY_CELL_CONDITION_LOST"
    assert errors[0]["path"] == ["cells", 0, "conditions", "*"]
    assert "sk-private" not in str(errors)


def test_budget_is_persisted_before_calls_and_resume_keeps_limit(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    request = request.model_copy(update={"maximum_api_calls": 2})
    first = service.discover(request)
    assert first.outcome == "deferred" and first.api_calls_used == 2
    second = service.discover(request)
    assert second.api_calls_used == 2 and len(provider.calls) == 2
    assert "DISCOVERY_API_BUDGET_EXHAUSTED" in second.reason_codes


def test_shared_budget_survives_changed_model_or_purpose(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    request = request.model_copy(update={"maximum_api_calls": 2, "budget_id": uuid4()})
    first = service.discover(request)
    assert first.api_calls_used == 2
    changed = request.model_copy(update={"editorial_intent": "通知方式を調べる"})
    second = service.discover(changed)
    assert second.api_calls_used == 2 and len(provider.calls) == 2
    assert "DISCOVERY_API_BUDGET_EXHAUSTED" in second.reason_codes


def test_changed_budget_limit_reuses_completed_stages(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    request = request.model_copy(update={"maximum_api_calls": 2, "budget_id": uuid4()})
    assert service.discover(request).api_calls_used == 2
    expanded = request.model_copy(update={"maximum_api_calls": 5})
    audit = service.discover(expanded)
    assert audit.outcome == "eligible" and audit.api_calls_used == 5
    assert len(provider.calls) == 5
    assert sum(call["model"] == "planner-test" for call in provider.calls) == 1


def test_cached_stage_rechecks_actual_input_identity(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    audit = service.discover(request)
    run = acquisition_session.get(AiRun, audit.groups[0].plan.ai_run_id)
    run.input_hash = "sha256:" + "0" * 64
    with pytest.raises(EditorialError, match="DISCOVERY_STAGE_RECORD_INVALID"):
        service.discover(request)
    assert len(provider.calls) == 5


def test_tampered_budget_ledger_never_creates_extra_calls(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    service.discover(request)
    row = acquisition_session.scalar(
        select(ModuleMessage).where(ModuleMessage.consumer == "comparison_discovery_budget")
    )
    row.payload_json = {**row.payload_json, "ordinal": 999}
    with pytest.raises(EditorialError, match="PAYLOAD_HASH_MISMATCH"):
        service.discover(request)
    assert len(provider.calls) == 5


def test_same_actual_review_model_rejected_before_ai(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    service.runner.settings = service.settings.model_copy(
        update={"ai_comparison_verifier_model": "planner-test"}
    )
    with pytest.raises(EditorialError, match="DISCOVERY_INDEPENDENT_MODEL_REQUIRED"):
        service.discover(request)
    assert not provider.calls


def test_frozen_group_rechecks_actual_models_and_current_sources(acquisition_session):
    from app.contracts.envelope import canonical_payload_hash

    service, request, _, provider = setup(acquisition_session)
    audit = service.discover(request)
    group = service.validate_frozen(audit)
    assert group.accepted and len(provider.calls) == 5
    review = acquisition_session.get(AiRun, group.independent_ai_run_id)
    review.model = "planner-test"
    with pytest.raises(EditorialError, match="DISCOVERY_INDEPENDENT_MODEL_REQUIRED"):
        service.validate_frozen(audit)
    review.model = "independent-test"
    extraction = acquisition_session.scalar(
        select(ExtractionResult).where(ExtractionResult.item_id == request.seed_item_id)
    )
    extraction.payload_json = {**extraction.payload_json, "title": "Changed source"}
    extraction.payload_hash = canonical_payload_hash(extraction.payload_json)
    with pytest.raises(EditorialError, match="DISCOVERY_FROZEN_SOURCE_CHANGED"):
        service.validate_frozen(audit)
    assert len(provider.calls) == 5


def test_frozen_content_cannot_be_changed_after_independent_review(acquisition_session):
    from app.core.comparison_discovery import frozen_group

    service, request, _, _ = setup(acquisition_session)
    audit = service.discover(request)
    group = audit.groups[0]
    changed_plan = group.plan.model_copy(
        update={
            "hypothesis": group.plan.hypothesis.model_copy(
                update={"selection_question": "Altered choice question"}
            )
        }
    )
    altered = audit.model_copy(
        update={"groups": (group.model_copy(update={"plan": changed_plan}),)}
    )
    with pytest.raises(EditorialError, match="DISCOVERY_FROZEN_HASH_MISMATCH"):
        frozen_group(altered)


def test_frozen_quotes_rebound_from_actual_source_even_with_recomputed_hash(acquisition_session):
    from app.contracts.envelope import canonical_payload_hash

    service, request, _, provider = setup(acquisition_session)
    audit = service.discover(request)
    group = audit.groups[0]
    entry = group.evaluations[0]
    reason = entry.evaluation.reason
    forged = reason.evidence[0].model_copy(update={"quote": "Forged quote"})
    entry = entry.model_copy(
        update={
            "evaluation": entry.evaluation.model_copy(
                update={
                    "reason": reason.model_copy(update={"evidence": (forged, *reason.evidence[1:])})
                }
            )
        }
    )
    group = group.model_copy(update={"evaluations": (entry, *group.evaluations[1:])})
    altered = audit.model_copy(
        update={
            "groups": (group,),
            "frozen_hash": canonical_payload_hash(group.model_dump(mode="json")),
        }
    )
    with pytest.raises(EditorialError, match="DISCOVERY_FROZEN_GROUNDING_CHANGED"):
        service.validate_frozen(altered)
    assert len(provider.calls) == 5


def test_joint_plan_requires_actual_support_for_all_major_cells(acquisition_session):
    from app.core.comparison_discovery import validate_hypothesis

    service, request, sources, _ = setup(acquisition_session)
    hypothesis = service.discover(request).groups[0].plan.hypothesis
    own = {s.document.item_id: s for s in sources}
    empty = hypothesis.model_copy(update={"question_support": ()})
    with pytest.raises(EditorialError, match="DISCOVERY_QUESTION_SUPPORT_REQUIRED"):
        validate_hypothesis(empty, own, require_support=True)
    cell = hypothesis.question_support[0]
    unknown = cell.model_copy(
        update={
            "cell": cell.cell.model_copy(
                update={"status": "unknown", "answer": "未記載", "fact_ids": (), "conditions": ()}
            )
        }
    )
    missing = hypothesis.model_copy(
        update={"question_support": (unknown, *hypothesis.question_support[1:])}
    )
    with pytest.raises(EditorialError, match="DISCOVERY_PROPOSED_MAJOR_UNSUPPORTED"):
        validate_hypothesis(missing, own, require_support=True)
    foreign = cell.model_copy(
        update={
            "cell": cell.cell.model_copy(
                update={
                    "fact_ids": (
                        next(s for s in sources if s.document.item_id != cell.item_id)
                        .evidence.verified_facts[0]
                        .fact_id,
                    )
                }
            )
        }
    )
    bad = hypothesis.model_copy(
        update={"question_support": (foreign, *hypothesis.question_support[1:])}
    )
    with pytest.raises(EditorialError):
        validate_hypothesis(bad, own, require_support=True)


def test_plan_repair_diagnostic_points_to_exact_support_cell(acquisition_session):
    from app.ai.diagnostics import validation_diagnostics
    from app.contracts.comparison_discovery_v2 import ComparisonGroupProposalV2
    from app.core.comparison_discovery import validate_hypothesis

    service, request, sources, _ = setup(acquisition_session)
    hypothesis = service.discover(request).groups[0].plan.hypothesis
    support = hypothesis.question_support[1]
    altered = support.model_copy(
        update={"cell": support.cell.model_copy(update={"as_of": "undocumented-date-do-not-log"})}
    )
    hypothesis = hypothesis.model_copy(
        update={
            "question_support": (
                hypothesis.question_support[0],
                altered,
                *hypothesis.question_support[2:],
            )
        }
    )
    with pytest.raises(EditorialError) as exc:
        validate_hypothesis(
            hypothesis, {s.document.item_id: s for s in sources}, require_support=True
        )
    assert exc.value.code == "DISCOVERY_CELL_QUALIFIER_UNGROUNDED"
    assert exc.value.path == ("question_support", 1, "cell", "as_of")
    diagnostic = validation_diagnostics(exc.value, ComparisonGroupProposalV2, 1)
    assert diagnostic[0]["path"] == ["question_support", 1, "cell", "as_of"]
    assert "undocumented-date" not in str(diagnostic)


@pytest.mark.parametrize("field", ["purpose", "audience", "product_reason"])
def test_plan_judgment_numeric_diagnostic_identifies_field_without_logging_text(
    acquisition_session, field
):
    from app.ai.diagnostics import validation_diagnostics
    from app.contracts.comparison_discovery_v2 import ComparisonGroupProposalV2
    from app.core.comparison_discovery import validate_hypothesis

    service, request, sources, _ = setup(acquisition_session)
    hypothesis = service.discover(request).groups[0].plan.hypothesis
    if field == "product_reason":
        reason = hypothesis.product_reasons[1]
        altered = reason.model_copy(
            update={"judgment": reason.judgment.model_copy(update={"text": "未記載987654321件"})}
        )
        hypothesis = hypothesis.model_copy(
            update={
                "product_reasons": (
                    hypothesis.product_reasons[0],
                    altered,
                    *hypothesis.product_reasons[2:],
                )
            }
        )
        path = ("product_reasons", 1, "judgment", "text")
    else:
        hypothesis = hypothesis.model_copy(
            update={
                field: getattr(hypothesis, field).model_copy(update={"text": "未記載987654321件"})
            }
        )
        path = (field, "text")
    with pytest.raises(EditorialError) as exc:
        validate_hypothesis(hypothesis, {s.document.item_id: s for s in sources})
    assert exc.value.code == "DISCOVERY_UNSUPPORTED_NUMBER"
    assert exc.value.path == path
    diagnostic = validation_diagnostics(exc.value, ComparisonGroupProposalV2, 1)
    assert diagnostic[0]["path"] == list(path)
    assert "987654321" not in str(diagnostic)


def test_plan_repair_receives_hypothesis_and_judgment_path(acquisition_session):
    service, request, _, provider = setup(acquisition_session, unsupported_number=True)
    assert service.discover(request).outcome == "deferred"
    assert len(provider.calls) == 2
    repair_instructions = provider.calls[1]["instructions"]
    assert '"path": ["hypotheses", 0, "purpose", "text"]' in repair_instructions
    assert "Previous typed candidate JSON:" in repair_instructions
    assert '"question_support":' in repair_instructions
    runs = [acquisition_session.get(AiRun, key) for key in service.runner.run_ids]
    assert all(run.output_json is None for run in runs)
    assert all("999999" not in str(run.validation_errors_json) for run in runs)


def test_inventory_repair_receives_typed_candidate_but_diagnostics_do_not_log_it(
    acquisition_session,
):
    service, request, _, provider = setup(acquisition_session, inventory_error="number")
    audit = service.discover(request.model_copy(update={"evidence_first": True}))
    assert audit.outcome == "deferred" and len(provider.calls) == 2
    instructions = provider.calls[1]["instructions"]
    assert '"path": ["dimensions", 0, "supports", 0, "cell", "answer"]' in instructions
    assert "Previous typed candidate JSON:" in instructions and "987654321" in instructions
    for key in service.runner.run_ids:
        run = acquisition_session.get(AiRun, key)
        assert run.output_json is None and "987654321" not in str(run.validation_errors_json)


def test_schema_invalid_discovery_output_never_enters_repair_context(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    original_generate = provider.generate

    def corrupt(**kwargs):
        response = original_generate(**kwargs)
        return AIResponse({**response.output, "forbidden_field": "do-not-forward-this-sentinel"})

    provider.generate = corrupt
    assert service.discover(request).outcome == "deferred"
    assert len(provider.calls) == 2
    assert "Previous typed candidate JSON:" not in provider.calls[1]["instructions"]
    assert "do-not-forward-this-sentinel" not in provider.calls[1]["instructions"]


def test_inventory_repair_receives_all_failed_cell_paths_without_logging_candidate(
    acquisition_session,
):
    service, request, _, provider = setup(acquisition_session, inventory_error="multiple_numbers")
    assert (
        service.discover(request.model_copy(update={"evidence_first": True})).outcome == "deferred"
    )
    instructions = provider.calls[1]["instructions"]
    assert '"path": ["dimensions", 0, "supports", 0, "cell", "answer"]' in instructions
    assert '"path": ["dimensions", 0, "supports", 2, "cell", "answer"]' in instructions
    assert "Previous typed candidate JSON:" in instructions
    for key in service.runner.run_ids:
        run = acquisition_session.get(AiRun, key)
        assert len(run.validation_errors_json) == 2
        assert "987654321" not in str(run.validation_errors_json)
        assert run.output_json is None


def test_parallel_budget_reservations_never_exceed_shared_limit(acquisition_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    service, request, _, _ = setup(acquisition_session)
    request = request.model_copy(update={"budget_id": uuid4(), "maximum_api_calls": 1})
    engine = acquisition_session.get_bind()
    barrier = Barrier(2)

    def worker(index):
        with Session(engine) as session:
            other = ComparisonDiscoveryService(session, service.settings, checkpoint=True)
            other.request = request
            other.request_hash = "sha256:parallel-test"
            barrier.wait(timeout=10)
            try:
                other.reserve("sha256:attempt-" + str(index))
                return "reserved"
            except EditorialError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (0, 1)))
    assert sorted(results) == ["DISCOVERY_API_BUDGET_EXHAUSTED", "reserved"]


def test_tampered_cached_stage_rejected(acquisition_session):
    service, request, _, provider = setup(acquisition_session)
    service.discover(request)
    row = acquisition_session.scalar(
        select(ModuleMessage).where(ModuleMessage.consumer == "comparison_discovery_stage")
    )
    row.payload_json = {**row.payload_json, "ai_run_id": str(uuid4())}
    with pytest.raises(EditorialError, match="PAYLOAD_HASH_MISMATCH"):
        service.discover(request)
    assert len(provider.calls) == 5


def test_keyword_retrieval_keeps_seed_and_japanese_similarity():
    seed, related, other = uuid4(), uuid4(), uuid4()
    ids, _ = rank_candidates(
        seed,
        {
            seed: "Web 脆弱性 診断 報告",
            related: "Web 脆弱性 検査 報告",
            other: "照明 温度 湿度 制御",
        },
    )
    assert ids == (seed, related, other)
    assert reciprocal_rank_fusion([seed, related], [related, related, other])[related] == (
        1 / 62 + 1 / 61
    )


def test_group_retrieval_records_all_combinations_and_diversifies_equally_related_groups():
    seed, a, b, c, d = (uuid4() for _ in range(5))
    texts = dict.fromkeys((seed, a, b, c, d), "脆弱性 診断 検知 報告")
    groups = rank_seeded_groups(seed, tuple(texts), texts)
    assert len(groups) == 6
    assert all(g.item_ids[0] == seed and g.relatedness == 1 for g in groups)
    assert not set(groups[0].item_ids[1:]) & set(groups[1].item_ids[1:])
    assert groups[1].redundancy == 0 and groups[1].selection_score == pytest.approx(0.7)
    assert rank_seeded_groups(seed, tuple(texts), texts) == groups


def test_discover_cli_never_accepts_production_mode():
    from typer.testing import CliRunner

    from app.cli import app

    result = CliRunner().invoke(
        app, ["comparison", "discover", "--seed", str(uuid4()), "--mode", "production"]
    )
    assert result.exit_code == 1 and "SHADOW_MODE_REQUIRED" in result.output


def test_vector_normalization_does_not_overflow():
    vector = Embedding("provider", "model", "revision", (1e308,) * 10)
    assert cosine(vector, vector) == pytest.approx(1.0)


def test_outgoing_context_masks_contacts_and_keeps_offsets(acquisition_session):
    service, _, sources, _ = setup(acquisition_session)
    source = replace(sources[0], body=sources[0].body + "\ncontact@example.com 03-1234-5678")
    data = service.source_context_data(source)
    for context in data["source_context"]:
        assert not personal_data(context["text"])
        assert len(context["text"]) == context["end"] - context["start"]


def test_context_coalescing_preserves_exact_windows_and_fact_mapping(acquisition_session):
    from app.core.comparison_discovery import coalesced_contexts, contexts

    _, _, sources, _ = setup(acquisition_session)
    for source in sources:
        windows = contexts(source)
        merged = coalesced_contexts(source)
        assert {i for w in windows for i in range(w.start, w.end)} == {
            i for w in merged for i in range(w.start, w.end)
        }
        assert {w.fact_id for w in windows} == {f for w in merged for f in w.fact_ids}
        assert sum(len(w.text) for w in merged) <= sum(len(w.text) for w in windows)
        assert all(w.text == source.body[w.start : w.end] for w in merged)


@pytest.mark.parametrize(
    "change",
    [
        {"model": "different"},
        {"revision": "different"},
        {"values": (1.0,)},
        {"values": (0.0, 0.0)},
        {"values": (nan, 1.0)},
    ],
)
def test_exact_vectors_reject_mixed_invalid_values(change):
    a = Embedding("provider", "model", "revision", (1.0, 2.0))
    with pytest.raises(ValueError):
        cosine(a, replace(a, **change))
    assert cosine(a, a) == pytest.approx(1.0)
