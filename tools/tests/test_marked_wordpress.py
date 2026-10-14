import copy

import pytest

from nw_generation.marked_comparison import (
    PROMPT,
    REQUIRED_CRITERIA,
    assessment_results,
    catalog,
    export_bundle,
    hashlib_text,
    prepare_document,
    schema,
)
from nw_generation.protocol import ProtocolError, read_bundle


def fixture():
    sources = [
        {
            "f_id": f"F{i}",
            "url": f"https://example.test/release/{i}",
            "title": f"Product {i}",
            "text": f"Product {i} supports a recorded feature.",
            "input_hash": hashlib_text(f"Product {i} supports a recorded feature."),
        }
        for i in range(3)
    ]
    raw = {
        "id": "X",
        "article_markdown": "# Original\n\nRecorded overview.\n\n| Item | P0 | P1 | P2 |\n|---|---|---|---|\n| Feature | Value | Value | Value |\n",  # noqa: E501
        "sources": sources,
        "source_article_ids": [s["f_id"] for s in sources],
        "generation_record": {
            "comparison_status": "eligible",
            "issues": [],
            "generation_checks": {},
        },
    }
    doc = prepare_document(raw, "Recorded comparison", {"model": "writer-original"})
    cat = catalog([doc])
    ar = cat["article_passages"][0]["ref"]
    check = {
        "status": "pass",
        "reason": "Recorded",
        "evidence": [{"source_ref": "F0:0000", "article_ref": ar}],
    }
    value = {
        "reader_context": "One reader",
        "decision_question": "One decision",
        "comparison_mode": "workflow_design",
        "distinct_targets": copy.deepcopy(check),
        "common_decision": {**copy.deepcopy(check), "decision_connection": "Recorded connection"},
        "source_fidelity": copy.deepcopy(check),
        "comparison_status": "eligible",
        "claims": {
            s["f_id"]: [
                {
                    "article_ref": ar,
                    "source_refs": [s["f_id"] + ":0000"],
                    "status": "supported",
                    "reason": "Supported",
                }
            ]
            for s in sources
        },
        "editorial_checks": {k: copy.deepcopy(check) for k in REQUIRED_CRITERIA},
        "category_keys": ["iot_platform"],
        "quality": {"test_axis": {"score": 10, "reason": "Recorded", "article_ref": ar}},
    }
    return doc, {"articles": {"X": value}, "pair_checks": {}}


def test_single_A_schema_does_not_lock_source_fidelity_to_pass():
    d, _ = fixture()
    s = schema([d], {"dimensions": [{"key": "test_axis", "max": 10}]})
    assert s["$defs"]["check"]["properties"]["status"]["enum"] == ["pass", "fail", "uncertain"]
    assert "原資料忠実性のstatusは自分で判定" in PROMPT


def test_complete_pass_exports_immutable_bound_article(tmp_path):
    d, output = fixture()
    result = assessment_results([d], output)[0]
    call = {
        "model": "verifier-other",
        "response_id": "saved",
        "request_sha256": "a" * 64,
        "completed_at": "2026-10-14T00:00:00+00:00",
    }
    path = export_bundle(d, result, call, tmp_path)
    initial = path.read_bytes()
    assert export_bundle(d, result, call, tmp_path).read_bytes() == initial
    meta, files = read_bundle(path, draft=True)
    assert meta["eligibility"]["verification"] == "pass"
    assert files["article.md"] == d["markdown"].encode()
    assert len(meta["source_urls"]) == 3 and meta["image_skip_reason"] == "disabled"
    from bs4 import BeautifulSoup

    links = {a["href"] for a in BeautifulSoup(files["article.html"], "html.parser").find_all("a")}
    assert set(meta["source_urls"]) <= links


@pytest.mark.parametrize("gate", ["distinct_targets", "common_decision", "source_fidelity"])
def test_failed_gate_cannot_be_rescued_by_quality(gate):
    d, output = fixture()
    a = output["articles"]["X"]
    a[gate]["status"] = "fail"
    a["comparison_status"] = "ineligible"
    if gate == "source_fidelity":
        a["claims"]["F0"][0].update(status="unsupported", source_refs=[])
    r = assessment_results([d], output)[0]
    assert not r["ready"] and r["normal_score"] is None
    assert "CONDITIONAL_QUALITY_INCONSISTENT" in r["technical_errors"]


def test_unsupported_claim_blocks_inconsistent_pass():
    d, output = fixture()
    output["articles"]["X"]["claims"]["F0"][0].update(status="unsupported", source_refs=[])
    r = assessment_results([d], output)[0]
    assert not r["ready"] and "SOURCE_FIDELITY_INCONSISTENT" in r["technical_errors"]


def test_editorial_failure_is_not_exportable(tmp_path):
    d, output = fixture()
    output["articles"]["X"]["editorial_checks"]["rights"]["status"] = "fail"
    r = assessment_results([d], output)[0]
    assert not r["ready"] and r["normal_score"] is None
    with pytest.raises(ProtocolError, match="A_RESULT_NOT_EXPORTABLE"):
        export_bundle(d, r, {}, tmp_path)


def test_wrong_article_evidence_blocks_result():
    d, output = fixture()
    output["articles"]["X"]["common_decision"]["evidence"][0]["article_ref"] = "OTHER:0000"
    assert not assessment_results([d], output)[0]["ready"]


def test_generation_and_recorded_negative_mark_block_preparation():
    _d, _ = fixture()
    raw = {"generation_record": {"comparison_status": "ineligible"}}
    with pytest.raises(ProtocolError, match="GENERATION_MARK_BLOCKED"):
        prepare_document(raw, "Title", {})
    raw = {
        "generation_record": {"comparison_status": "eligible"},
        "common_verification": {"comparison_status": "ineligible"},
    }
    with pytest.raises(ProtocolError, match="RECORDED_REJECTION_BLOCKED"):
        prepare_document(raw, "Title", {})


def test_byte_or_package_tamper_blocks_export(tmp_path):
    d, output = fixture()
    r = assessment_results([d], output)[0]
    d["markdown"] += "\nChanged."
    with pytest.raises(ProtocolError, match="DRAFT_HASH_MISMATCH"):
        export_bundle(d, r, {}, tmp_path)


def test_all_pairs_and_hash_guard():
    d, output = fixture()
    other = copy.deepcopy(d)
    other["id"] = "Y"
    value = copy.deepcopy(output["articles"]["X"])
    ar = catalog([other])["article_passages"][0]["ref"]
    for c in [value[k] for k in ["distinct_targets", "common_decision", "source_fidelity"]] + list(
        value["editorial_checks"].values()
    ):
        c["evidence"][0]["article_ref"] = ar
    for claims in value["claims"].values():
        claims[0]["article_ref"] = ar
    value["quality"]["test_axis"]["article_ref"] = ar
    output["articles"]["Y"] = value
    with pytest.raises(ProtocolError, match="PAIR_OUTPUT_MISSING"):
        assessment_results([d, other], output)
    output["pair_checks"]["X|Y"] = {
        "relation": "distinct",
        "reason": "mock",
        "left_article_ref": catalog([d])["article_passages"][0]["ref"],
        "right_article_ref": ar,
        "representative": "",
    }
    results = assessment_results([d, other], output)
    assert sum(r["ready"] for r in results) == 1
    assert sum(r["normal_score"] is not None for r in results) == 1


def test_required_claim_units_and_shared_schema_definitions():
    from nw_generation.marked_comparison import claim_units, validate_schema

    d, old = fixture()
    v = old["articles"]["X"]
    v["subject_roles"] = {
        fid: {
            "role_in_one_decision": "Recorded role",
            "article_ref": catalog([d])["article_passages"][0]["ref"],
        }
        for fid in d["source_article_ids"]
    }
    v["claims"] = {
        fid: {
            u["unit_id"]: {
                "source_refs": [fid + ":0000"],
                "status": "supported",
            }
            for u in claim_units(d)
            if fid in u["source_ids"]
        }
        for fid in d["source_article_ids"]
    }
    s = schema([d], {"dimensions": [{"key": "test_axis", "max": 10}]})
    validate_schema(old, s)
    assert assessment_results([d], old)[0]["ready"]
    removed = next(iter(v["claims"]["F0"]))
    del v["claims"]["F0"][removed]
    with pytest.raises(AssertionError):
        validate_schema(old, s)
    assert "CLAIM_UNIT_COVERAGE_INCOMPLETE" in assessment_results([d], old)[0]["technical_errors"]


def test_editorial_and_unknown_labels_are_not_product_claim_failures():
    d, output = fixture()
    output["articles"]["X"]["claims"]["F0"][0].update(status="editorial_statement", source_refs=[])
    output["articles"]["X"]["claims"]["F1"][0].update(status="not_stated", source_refs=[])
    result = assessment_results([d], output)[0]
    assert result["ready"] and not result["technical_errors"]


def test_no_drafts_is_not_a_successful_handoff(tmp_path, monkeypatch):
    from tools import check_marked_wordpress_handoff as checker

    monkeypatch.setattr(checker, "OUT", tmp_path)
    (tmp_path / "handoff.json").write_text('{"drafts":[]}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="NO_ELIGIBLE_DRAFTS"):
        checker.main()
