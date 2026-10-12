from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from app.ai.dynamic_axes_prompts import DISCOVER, EXTRACT, REPAIR, REVIEW, SELECT
from app.ai.provider import AIResponse
from app.ai.runner import AIRunner
from app.contracts.comparison_dynamic_axes_v1 import (
    AxisCandidates,
    AxisSelection,
    AxisValues,
    DynamicAxesRequest,
)
from app.contracts.comparison_pair_discovery_v3 import PairDocument
from app.core.comparison_dynamic_axes import (
    axis_coverage,
    validate_candidates,
    validate_documents,
    validate_selection,
    validate_values,
)
from app.core.comparison_pair_discovery import text_hash
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.infrastructure.db.models import AiRun, ArticleDraft, Item, Publication, Source
from app.orchestration.comparison_dynamic_axes import DynamicAxesService, export_run


def documents(session, count=3):
    source = session.scalar(select(Source))
    result = []
    for index in range(count):
        body = f"Acme{index} Widget{index} uses LTE and MQTT. Monthly fee 100 JPY."
        item = Item(
            id=uuid4(),
            source_id=source.id,
            external_id=str(uuid4()),
            canonical_url=f"https://example.com/{uuid4()}",
            title_original=f"Widget{index}",
            language="en",
            content_text=body,
            content_sha256=text_hash(body),
            published_at=datetime.now(UTC),
        )
        session.add(item)
        session.flush()
        result.append(
            PairDocument(
                item_id=item.id,
                item_version=1,
                snapshot_id=uuid4(),
                source_id=source.id,
                url=item.canonical_url,
                title=item.title_original,
                body=body,
                body_hash=text_hash(body),
            )
        )
    session.commit()
    return tuple(result)


def quote(doc):
    return {"item_id": str(doc.item_id), "start": 0, "end": len(doc.body), "quote": doc.body}


def candidates(docs):
    return AxisCandidates.model_validate(
        {
            "axes": [
                {
                    "axis_id": str(i),
                    "label": label,
                    "question": label + "は何か?",
                    "layer": layer,
                    "search_terms": {1: ["LTE"], 2: ["MQTT"], 3: ["fee"]}[i],
                    "evidence": [quote(docs[0])],
                }
                for i, label, layer in (
                    (1, "通信方式", "input"),
                    (2, "連携インターフェース", "output"),
                    (3, "課金条件", "operations"),
                )
            ]
        }
    )


def values(doc, axes, missing=(), name=None):
    return AxisValues.model_validate(
        {
            "product": {
                "item_id": str(doc.item_id),
                "name": name or doc.title,
                "organization": doc.body.split()[0],
                "evidence": [quote(doc)],
            },
            "cells": [
                {
                    "axis_id": a.axis_id,
                    "status": "unknown" if a.axis_id in missing else "supported",
                    "answer": ""
                    if a.axis_id in missing
                    else {"1": "LTE", "2": "MQTT", "3": "100 JPY"}[a.axis_id],
                    "conditions": "",
                    "evidence": [] if a.axis_id in missing else [quote(doc)],
                }
                for a in axes
            ],
        }
    )


class Provider:
    def __init__(self, docs, *, review_ok=True, empty=False):
        self.docs = {str(d.item_id): d for d in docs}
        self.calls = []
        self.review_ok, self.empty = review_ok, empty
        self.candidates = candidates(docs)

    def generate(self, **kwargs):
        data, prompt = kwargs["data"], kwargs["instructions"]
        self.calls.append(prompt)
        if prompt == DISCOVER:
            output = {"axes": []} if self.empty else self.candidates.model_dump(mode="json")
        elif prompt in {EXTRACT, REPAIR}:
            output = values(self.docs[data["source"]["item_id"]], self.candidates.axes).model_dump(
                mode="json"
            )
        elif prompt == SELECT:
            output = {
                "purpose": "遠隔監視製品を選ぶ",
                "same_selection_task": True,
                "selected_axis_ids": data["eligible_axis_ids"],
                "assessments": [
                    {
                        "axis_id": a["axis_id"],
                        "answers_fit_question": True,
                        "useful": True,
                        "distinct": True,
                        "reason": "選択条件",
                    }
                    for a in data["axes"]
                ],
                "reason": "根拠あり",
            }
        elif prompt == REVIEW:
            output = {
                "same_selection_task": True,
                "checks": [
                    {
                        "axis_id": a["axis_id"],
                        "answers_fit_question": True,
                        "evidence_valid": True,
                        "conditions_preserved": self.review_ok,
                        "useful": True,
                        "distinct": True,
                        "reason": "原文照合",
                    }
                    for a in data["axes"]
                ],
                "reason": "独立検証",
            }
        else:
            raise AssertionError("unexpected prompt")
        if prompt in {DISCOVER, EXTRACT, REPAIR}:

            def refs(node):
                if isinstance(node, dict):
                    if {"item_id", "start", "end", "quote"} <= node.keys():
                        return {"item_id": node["item_id"], "passage_id": "p0000"}
                    return {k: refs(v) for k, v in node.items()}
                if isinstance(node, list):
                    return [refs(v) for v in node]
                return node

            output = refs(output)
        return AIResponse(output, input_tokens=10, output_tokens=20, latency_ms=1)


def settings():
    return Settings(
        _env_file=None,
        ai_comparison_planner_model="planner",
        ai_comparison_assessor_model="extractor",
        ai_comparison_verifier_model="reviewer",
    )


def test_discovery_does_not_mix_responsibilities():
    assert "未記載" not in DISCOVER
    assert "非対応" not in DISCOVER
    assert "順位" not in DISCOVER
    assert "same_selection_task" not in DISCOVER
    assert set(AxisCandidates.model_fields) == {"axes"}


@pytest.mark.parametrize("count", [9, 24])
def test_discovery_preserves_more_than_eight_candidates(acquisition_session, count):
    from app.contracts.comparison_dynamic_axes_v1 import AxisCandidatesRef
    from app.core.comparison_dynamic_axes import resolve_evidence
    from app.orchestration.comparison_dynamic_axes import document_data

    docs = documents(acquisition_session)
    provider = Provider(docs)
    template = provider.candidates.axes[0]
    provider.candidates = AxisCandidates(
        axes=tuple(
            template.model_copy(
                update={"axis_id": str(i), "label": f"項目{i}", "question": f"項目{i}は何か?"}
            )
            for i in range(count)
        )
    )
    for model in (AxisCandidates, AxisCandidatesRef):
        assert "maxItems" not in model.model_json_schema()["properties"]["axes"]
    result, run_id = AIRunner(acquisition_session, settings(), provider).run(
        "axis_discover",
        docs[0].item_id,
        {"sources": [document_data(d) for d in docs]},
        AxisCandidatesRef,
        validate=lambda value: validate_candidates(
            resolve_evidence(value, {d.item_id: d for d in docs}, AxisCandidates),
            {d.item_id: d for d in docs},
        ),
    )
    assert result is not None
    assert len(result.axes) == count
    assert [a.axis_id for a in result.axes] == [str(i) for i in range(count)]
    assert provider.calls == [DISCOVER]
    assert acquisition_session.get(AiRun, run_id).validation_status == "valid"


def test_axis_search_matches_aliases_without_ai(acquisition_session):
    from app.core.comparison_dynamic_axes import matching_axis_terms

    axes = candidates(documents(acquisition_session)).axes
    assert matching_axis_terms("monthly FEE and \uff2c\uff34\uff25", axes) == {
        "1": ("LTE",),
        "3": ("fee",),
    }
    assert matching_axis_terms("SILTE MQTTbridge coffee", axes) == {}
    assert matching_axis_terms("通信方式と連携インターフェース", axes) == {
        "1": ("通信方式",),
        "2": ("連携インターフェース",),
    }


@pytest.mark.parametrize(
    "label", ["価格\uff08セット別\uff09", "価格(通常)", "価格「通常」", "価格" * 13]
)
def test_axis_names_exclude_brackets_and_long_modifiers(acquisition_session, label):
    docs = documents(acquisition_session)
    result = candidates(docs)
    changed = result.axes[0].model_copy(update={"label": label})
    with pytest.raises(EditorialError, match="AXIS_LABEL_NOT_SEARCHABLE"):
        validate_candidates(
            result.model_copy(update={"axes": (changed,)}), {d.item_id: d for d in docs}
        )


@pytest.mark.parametrize(
    "terms", [(), ("LTE", "lte"), ("機能",), ("LTE|MQTT",), ("監視・制御できます",)]
)
def test_axis_search_rejects_empty_duplicate_and_generic_terms(acquisition_session, terms):
    docs = documents(acquisition_session)
    result = candidates(docs)
    changed = result.axes[0].model_copy(update={"search_terms": terms})
    with pytest.raises(EditorialError, match="AXIS_SEARCH_TERMS_INVALID"):
        validate_candidates(
            result.model_copy(update={"axes": (changed,)}), {d.item_id: d for d in docs}
        )


def test_search_term_normalization_keeps_only_observed_aliases(acquisition_session):
    from app.contracts.comparison_dynamic_axes_v1 import AxisCandidatesRef
    from app.core.comparison_dynamic_axes import grounded_search_terms, resolve_evidence

    docs = documents(acquisition_session)
    by_id = {d.item_id: d for d in docs}
    payload = candidates(docs).model_dump(mode="json")
    for axis in payload["axes"]:
        axis["evidence"] = [{"item_id": str(docs[0].item_id), "passage_id": "p0000"}]
    payload["axes"][0]["search_terms"] = ["LTE", "Bluetooth", "lte"]
    refs = grounded_search_terms(AxisCandidatesRef.model_validate(payload), by_id)
    assert refs.axes[0].search_terms == ("LTE",)
    validate_candidates(resolve_evidence(refs, by_id, AxisCandidates), by_id)
    payload["axes"][0]["search_terms"] = ["Bluetooth"]
    empty = grounded_search_terms(AxisCandidatesRef.model_validate(payload), by_id)
    with pytest.raises(EditorialError, match="AXIS_SEARCH_TERMS_INVALID"):
        validate_candidates(resolve_evidence(empty, by_id, AxisCandidates), by_id)


def test_shared_search_excludes_single_article_details(acquisition_session):
    from app.contracts.comparison_dynamic_axes_v1 import AxisCandidatesRef
    from app.core.comparison_dynamic_axes import resolve_evidence, shared_search_candidates

    docs = documents(acquisition_session)
    first = docs[0].model_copy(update={"body": docs[0].body + " RareDetail"})
    by_id = {d.item_id: d for d in (first, *docs[1:])}
    payload = candidates(docs).model_dump(mode="json")
    for axis in payload["axes"]:
        axis["evidence"] = [{"item_id": str(first.item_id), "passage_id": "p0000"}]
    payload["axes"][0]["search_terms"] = ["RareDetail"]
    refs = AxisCandidatesRef.model_validate(payload)
    with pytest.raises(EditorialError, match="AXIS_SEARCH_NOT_SHARED"):
        validate_candidates(resolve_evidence(refs, by_id, AxisCandidates), by_id)
    common = shared_search_candidates(refs, by_id)
    assert [a.axis_id for a in common.axes] == ["2", "3"]
    validate_candidates(resolve_evidence(common, by_id, AxisCandidates), by_id)


def test_brand_and_broad_action_forms_are_removed(acquisition_session):
    from app.contracts.comparison_dynamic_axes_v1 import AxisCandidatesRef
    from app.core.comparison_dynamic_axes import grounded_search_terms

    docs = documents(acquisition_session)
    first = docs[0].model_copy(
        update={"body": docs[0].body + " 株式会社Acme Acmeクラウド 更新 一括"}
    )
    payload = candidates(docs).model_dump(mode="json")
    for axis in payload["axes"]:
        axis["evidence"] = [{"item_id": str(first.item_id), "passage_id": "p0000"}]
    payload["axes"][0]["search_terms"] = ["LTE", "Acmeクラウド", "更新", "一括"]
    cleaned = grounded_search_terms(
        AxisCandidatesRef.model_validate(payload), {d.item_id: d for d in (first, *docs[1:])}
    )
    assert cleaned.axes[0].search_terms == ("LTE",)


def test_every_search_alias_is_grounded_in_its_axis_evidence(acquisition_session):
    docs = documents(acquisition_session)
    result = candidates(docs)
    changed = result.axes[0].model_copy(update={"search_terms": ("LTE", "Bluetooth")})
    with pytest.raises(EditorialError, match="AXIS_SEARCH_TERM_UNGROUNDED"):
        validate_candidates(
            result.model_copy(update={"axes": (changed,)}), {d.item_id: d for d in docs}
        )


@pytest.mark.parametrize("size,supported,accepted", [(3, 2, True), (4, 2, False), (5, 3, True)])
def test_post_extraction_majority(acquisition_session, size, supported, accepted):
    docs = documents(acquisition_session, size)
    axes = candidates(docs).axes
    result = tuple(
        values(d, axes, missing=("1",) if i >= supported else ()) for i, d in enumerate(docs)
    )
    counts = axis_coverage(result, axes)
    assert counts["1"] == supported
    selection = AxisSelection(
        purpose="監視",
        same_selection_task=True,
        selected_axis_ids=("1",),
        assessments=tuple(
            {
                "axis_id": a.axis_id,
                "answers_fit_question": True,
                "useful": True,
                "distinct": True,
                "reason": "対象",
            }
            for a in axes
        ),
        reason="選定",
    )
    if accepted:
        validate_selection(selection, axes, counts, size)
    else:
        with pytest.raises(EditorialError, match="AXIS_SELECTION_UNSUPPORTED"):
            validate_selection(selection, axes, counts, size)


def test_free_labels_and_frozen_cells(acquisition_session):
    docs = documents(acquisition_session)
    axes = candidates(docs)
    validate_candidates(axes, {d.item_id: d for d in docs})
    good = values(docs[0], axes.axes)
    validate_values(good, docs[0], axes.axes)
    with pytest.raises(EditorialError, match="AXIS_CELL_SET_INVALID"):
        validate_values(good.model_copy(update={"cells": good.cells[:2]}), docs[0], axes.axes)
    bad = good.model_copy(
        update={
            "cells": (
                good.cells[0].model_copy(
                    update={
                        "evidence": (
                            *good.cells[0].evidence,
                            good.cells[0]
                            .evidence[0]
                            .model_copy(update={"item_id": docs[1].item_id}),
                        )
                    }
                ),
                *good.cells[1:],
            )
        }
    )
    with pytest.raises(EditorialError, match="PAIR_GROUNDING_INVALID"):
        validate_values(bad, docs[0], axes.axes)


def test_duplicate_documents_and_products(acquisition_session):
    docs = documents(acquisition_session)
    with pytest.raises(EditorialError, match="AXIS_DUPLICATE_DOCUMENT"):
        validate_documents((docs[0], docs[0], docs[1]))
    axes = candidates(docs).axes
    first = values(docs[0], axes)
    second = values(docs[1], axes).model_copy(
        update={"product": first.product.model_copy(update={"item_id": docs[1].item_id})}
    )
    with pytest.raises(EditorialError, match="AXIS_DUPLICATE_PRODUCT"):
        axis_coverage((first, second, values(docs[2], axes)), axes)


@pytest.mark.parametrize("size", [3, 4, 5])
def test_checkpoint_resume_and_export(acquisition_session, tmp_path, size):
    docs = documents(acquisition_session, size)
    provider = Provider(docs)
    runner = AIRunner(acquisition_session, settings(), provider)
    service = DynamicAxesService(acquisition_session, settings(), runner)
    request = DynamicAxesRequest(documents=docs)
    partial = service.run(request, call_budget=2)
    assert partial.status == "paused_budget"
    assert partial.ai_calls == 2
    state = service.run(request, call_budget=20)
    assert state.status == "selection_passed"
    assert len(provider.calls) == size + 3
    assert all(a.layer != "mechanism" for a in state.candidates.axes)
    assert len(state.selection.selected_axis_ids) == 3
    export_run(acquisition_session, request.run_id, tmp_path)
    assert (tmp_path / "selection.json").exists()
    assert (tmp_path / "comparison.md").exists()
    assert (tmp_path / "coverage.csv").exists()
    import json

    search = json.loads((tmp_path / "axis-search.json").read_text(encoding="utf-8"))
    assert search["match_kind"] == "literal_mention"
    assert len(search["documents"]) == size
    assert set(search["documents"][0]["matches"]) == {"1", "2", "3"}
    assert list(acquisition_session.scalars(select(ArticleDraft))) == []
    assert list(acquisition_session.scalars(select(Publication))) == []
    assert len(list(acquisition_session.scalars(select(AiRun)))) == size + 3
    assert {
        r.item_id
        for r in acquisition_session.scalars(
            select(AiRun).where(AiRun.execution_role == "axis_extract")
        )
    } == {d.item_id for d in docs}
    changed = settings().model_copy(update={"ai_comparison_planner_model": "changed"})
    with pytest.raises(EditorialError, match="AXIS_RESUME_CONFIGURATION_CHANGED"):
        DynamicAxesService(acquisition_session, changed).run(request)


@pytest.mark.parametrize("review_ok,empty", [(False, False), (True, True)])
def test_hold_not_forced_to_pass(acquisition_session, tmp_path, review_ok, empty):
    docs = documents(acquisition_session)
    provider = Provider(docs, review_ok=review_ok, empty=empty)
    runner = AIRunner(acquisition_session, settings(), provider)
    request = DynamicAxesRequest(documents=docs)
    state = DynamicAxesService(acquisition_session, settings(), runner).run(request)
    assert state.status == "held"
    assert len(provider.calls) == (1 if empty else 11)
    export_run(acquisition_session, request.run_id, tmp_path)
    assert not (tmp_path / "selection.json").exists()


def test_discovery_only_needs_one_model_and_stops_before_values(acquisition_session, tmp_path):
    import json

    docs = documents(acquisition_session)
    provider = Provider(docs)
    only = settings().model_copy(
        update={"ai_comparison_assessor_model": "", "ai_comparison_verifier_model": ""}
    )
    service = DynamicAxesService(
        acquisition_session, only, AIRunner(acquisition_session, only, provider)
    )
    request = DynamicAxesRequest(documents=docs, mode="discovery_only")
    state = service.run(request, call_budget=1)
    assert state.status == "candidates_ready"
    assert provider.calls == [DISCOVER]
    assert state.values == () and state.selection is None and state.review is None
    export_run(acquisition_session, request.run_id, tmp_path)
    assert len(json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))["axes"]) == 3
    assert (tmp_path / "axis-search.json").exists()
    assert not (tmp_path / "comparison.md").exists()
    assert service.run(request).status == "candidates_ready"
    assert provider.calls == [DISCOVER]


def test_cli_help():
    from app.cli import app

    result = CliRunner().invoke(app, ["comparison-axes", "--help"])
    assert result.exit_code == 0
    assert all(command in result.stdout for command in ("discover", "resume", "export"))
    assert (
        "discovery-only"
        in CliRunner().invoke(app, ["comparison-axes", "discover", "--help"]).stdout
    )


def test_passage_ids_resolve_repeated_text_without_guessing(acquisition_session):
    from app.contracts.comparison_dynamic_axes_v1 import AxisCandidatesRef
    from app.core.comparison_dynamic_axes import resolve_evidence, source_passages

    docs = documents(acquisition_session)
    body = docs[0].body + "\n\nLTE MQTT\n\nLTE MQTT"
    doc = docs[0].model_copy(update={"body": body, "body_hash": text_hash(body)})
    passages = source_passages(doc)
    assert len(passages) == 3
    ref = AxisCandidatesRef.model_validate(
        {
            "axes": [
                {
                    "axis_id": "link",
                    "label": "通信",
                    "search_terms": ["LTE"],
                    "question": "通信方式は何か?",
                    "layer": "input",
                    "evidence": [{"item_id": str(doc.item_id), "passage_id": "p0002"}],
                }
            ]
        }
    )
    result = resolve_evidence(ref, {doc.item_id: doc}, AxisCandidates)
    quote_ref = result.axes[0].evidence[0]
    assert quote_ref.start == body.rfind("LTE MQTT")
    assert doc.body[quote_ref.start : quote_ref.end] == quote_ref.quote
    invalid = ref.model_dump(mode="json")
    invalid["axes"][0]["evidence"][0]["passage_id"] = "p9999"
    with pytest.raises(EditorialError, match="AXIS_PASSAGE_INVALID"):
        resolve_evidence(
            AxisCandidatesRef.model_validate(invalid), {doc.item_id: doc}, AxisCandidates
        )


def test_unknown_and_explicit_negative_coverage(acquisition_session):
    docs = documents(acquisition_session)
    axes = candidates(docs).axes
    result = values(docs[0], axes, missing=("1",))
    invalid = result.model_copy(
        update={
            "cells": (result.cells[0].model_copy(update={"answer": "非対応"}), *result.cells[1:])
        }
    )
    with pytest.raises(EditorialError, match="AXIS_UNKNOWN_WITH_VALUE"):
        validate_values(invalid, docs[0], axes)
    negative = values(docs[1], axes)
    negative = negative.model_copy(
        update={
            "cells": (
                negative.cells[0].model_copy(update={"status": "not_supported"}),
                *negative.cells[1:],
            )
        }
    )
    assert axis_coverage((result, negative, values(docs[2], axes)), axes)["1"] == 2


def test_resume_rejects_modified_cached_output(acquisition_session):
    from app.infrastructure.db.models import ModuleMessage

    docs = documents(acquisition_session)
    runner = AIRunner(acquisition_session, settings(), Provider(docs))
    service = DynamicAxesService(acquisition_session, settings(), runner)
    request = DynamicAxesRequest(documents=docs)
    service.run(request, call_budget=1)
    row = acquisition_session.get(ModuleMessage, request.run_id)
    data = dict(row.result_json)
    stages = {key: dict(value) for key, value in data["stages"].items()}
    for stage in stages.values():
        stage["output"] = {"axes": []}
    row.result_json = {**data, "stages": stages}
    acquisition_session.commit()
    result = service.run(request)
    assert result.status == "waiting_retry"
    assert result.reason == "AXIS_AI_CACHE_INVALID"


def test_export_cannot_overwrite_other_run(acquisition_session, tmp_path):
    docs = documents(acquisition_session)
    request = DynamicAxesRequest(documents=docs)
    runner = AIRunner(acquisition_session, settings(), Provider(docs))
    DynamicAxesService(acquisition_session, settings(), runner).run(request)
    export_run(acquisition_session, request.run_id, tmp_path)
    original = (tmp_path / "selection.json").read_bytes()
    next_request = DynamicAxesRequest(documents=docs)
    next_runner = AIRunner(acquisition_session, settings(), Provider(docs, empty=True))
    DynamicAxesService(acquisition_session, settings(), next_runner).run(next_request)
    with pytest.raises(EditorialError, match="AXIS_EXPORT_RUN_MISMATCH"):
        export_run(acquisition_session, next_request.run_id, tmp_path)
    assert (tmp_path / "selection.json").read_bytes() == original


def test_cli_outputs_resumable_run_id(acquisition_session, monkeypatch, capsys):
    import json

    import typer

    from app import dynamic_axes_cli

    docs = documents(acquisition_session)
    request = DynamicAxesRequest(documents=docs)
    monkeypatch.setattr(dynamic_axes_cli, "SessionLocal", lambda: acquisition_session)
    monkeypatch.setattr(dynamic_axes_cli, "get_settings", settings)
    monkeypatch.setattr(
        dynamic_axes_cli,
        "DynamicAxesService",
        lambda session, cfg: DynamicAxesService(
            session, cfg, AIRunner(session, cfg, Provider(docs, empty=True))
        ),
    )
    with pytest.raises(typer.Exit) as exit_info:
        dynamic_axes_cli.execute(request, 20, None)
    assert exit_info.value.exit_code == 2
    assert json.loads(capsys.readouterr().out)["run_id"] == str(request.run_id)


def test_one_repair_round_resumes_and_rechecks(acquisition_session, tmp_path):
    from app.ai.dynamic_axes_prompts import REPAIR

    docs = documents(acquisition_session)

    class RecoveringProvider(Provider):
        def __init__(self, docs):
            super().__init__(docs)
            self.reviews = 0

        def generate(self, **kwargs):
            if kwargs["instructions"] == REVIEW:
                self.review_ok = self.reviews > 0
                self.reviews += 1
            response = super().generate(**kwargs)
            if kwargs["instructions"] == REPAIR:
                response.output["cells"][2]["conditions"] = "Monthly fee"
            return response

    provider = RecoveringProvider(docs)
    service = DynamicAxesService(
        acquisition_session, settings(), AIRunner(acquisition_session, settings(), provider)
    )
    request = DynamicAxesRequest(documents=docs)
    partial = service.run(request, call_budget=7)
    assert partial.status == "paused_budget"
    assert partial.repair_round == 1
    state = service.run(request, call_budget=20)
    assert state.status == "selection_passed"
    assert state.repair_round == 1
    assert not all(c.conditions_preserved for c in state.initial_review.checks)
    assert all(c.conditions_preserved for c in state.review.checks)
    assert state.ai_calls == 11
    assert provider.calls.count(REPAIR) == 3
    assert provider.reviews == 2
    assert state.candidates == candidates(docs)
    export_run(acquisition_session, request.run_id, tmp_path)
    assert (tmp_path / "selection.json").exists()
