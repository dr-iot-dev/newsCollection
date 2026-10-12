"""DB-free stage transport and execution regressions."""

from uuid import uuid4

import pytest

from app.ai.provider import AIResponse
from app.contracts.editorial_v1 import WritingOutputV1
from app.contracts.verification_v1 import VerificationReportV1
from nw_generation.common import Context, StageInput
from nw_generation.handlers import assemble, collect, curate, ground, illustrate, verify, write
from nw_generation.protocol import (
    ProtocolError,
    bundle_bytes,
    canonical,
    digest,
    load_json,
    process_lock,
    read_bundle,
    write_stage,
)
from nw_generation.runtime import execute


def evidence():
    assets, documents = {}, []
    for index, (company, product, spec) in enumerate(
        [
            ("ExampleCorp", "ABC100", 8),
            ("OtherCorp", "XYZ200", 16),
            ("ThirdCorp", "DEF300", 32),
        ]
    ):
        body = (
            f"Company: {company}\nProduct: {product}\n仕様: {spec}GB\n価格: 19,800円\n"
            "発売日: 2026年11月\n"
        ) + (
            f"The manufacturer released an edge AI gateway with a documented local interface "
            f"for industrial installations. The {product} provides primary release information "
            "with technical requirements and deployment conditions. "
        ) * 3
        # One source identity per article.
        body = body[: body.find("\nCompany:", 10)] if "\nCompany:" in body[10:] else body
        name = f"assets/{index}.txt"
        data = body.encode()
        assets[name] = data
        documents.append(
            {
                "item_id": str(uuid4()),
                "snapshot_id": str(uuid4()),
                "url": f"https://vendor.example/news/{index}",
                "title": f"{company} {product} edge AI gateway",
                "path": name,
                "sha256": digest(data),
                "fetched_at": "2026-10-12T00:00:00+00:00",
                "published_at": "2026-09-30T00:00:00+00:00",
                "language": "en",
                "is_html": False,
                "rights_approved": True,
            }
        )
    result = ground.run(
        {"sources": StageInput({}, {"documents": documents}, assets)}, {}, Context()
    )
    assert result.outcome == "success", result.issues
    kind, payload, files = result.outputs["evidence"]
    assert len(payload["documents"]) == 3
    return StageInput({"contract_type": kind}, payload, files)


def package():
    result = curate.run({"evidence": evidence()}, {}, Context())
    assert result.outcome == "success", result.issues
    kind, payload, assets = result.outputs["package"]
    return StageInput({"contract_type": kind}, payload, assets)


class Provider:
    def __init__(self):
        self.calls = []

    def generate(self, *, model, data, **kwargs):
        self.calls.append(model)
        if model == "writer-test":
            pack = data["package"]
            facts = pack["facts"]
            products = [f for f in facts if f["fact_type"] == "product"]
            specs = [f for f in facts if f["fact_type"] == "hardware_spec"]
            paragraphs = [
                {
                    "text": f"{p['value']} は {s['value']} の仕様を公表した。",
                    "fact_ids": [p["fact_id"], s["fact_id"]],
                }
                for p, s in zip(products, specs, strict=True)
            ]
            value = WritingOutputV1(
                title="ABC100 の製品仕様と選択条件",
                lead="確認できた製品仕様を整理する。",
                paragraphs=paragraphs,
                category_keys=("iot_platform",),
                importance=3,
            ).model_dump(mode="json")
        else:
            value = VerificationReportV1(
                verification_id=data["verification_id"],
                draft_id=data["draft"]["draft_id"],
                article_package_id=data["draft"]["article_package_id"],
                policy_version=data["policy_version"],
                verifier_profile_key=data["verifier_profile_key"],
                overall_result="pass",
                criteria=tuple(
                    {"key": key, "result": "pass", "detail": "verified"}
                    for key in data["required_criteria"]
                ),
            ).model_dump(mode="json")
        return AIResponse(value, "test-request", 100, 50, 1)


def stages():
    supplied = package()
    provider = Provider()
    context = Context(
        config={"models": {"writer": "writer-test", "verifier": "verifier-test"}}, provider=provider
    )
    outcome = write.run({"package": supplied}, {}, context)
    draft = StageInput({}, outcome.outputs["draft"][1])
    verified = verify.run({"package": supplied, "draft": draft}, {}, context)
    assert verified.outputs["verification"][1]["report"]["overall_result"] == "pass"
    verification = StageInput({}, verified.outputs["verification"][1])
    image = illustrate.run({"draft": draft}, {"enabled": False}, Context())
    return {
        "package": supplied,
        "draft": draft,
        "verification": verification,
        "image": StageInput({}, image.outputs["image"][1]),
    }


def test_complete_db_free_generation_is_deterministic():
    inputs = stages()
    parameters = {"producer_id": str(uuid4())}
    first = assemble.run(inputs, parameters, Context()).outputs["bundle"][2]["bundle.nwdraft"]
    second = assemble.run(inputs, parameters, Context()).outputs["bundle"][2]["bundle.nwdraft"]
    assert first == second
    meta, files = read_bundle(first, draft=True)
    assert meta["eligibility"]["verification"] == "pass"
    assert "writer-test" in files["article.html"].decode()
    assert "verifier-test" in files["article.html"].decode()
    assert len(meta["source_urls"]) == 3


def test_missing_sources_does_not_emit_fetch_plan_by_default():
    source = evidence()
    source.payload["documents"] = source.payload["documents"][:1]
    result = curate.run({"evidence": source}, {}, Context())
    assert result.outcome == "needs_input"
    assert result.issues[0]["code"] == "MISSING_SOURCE_FETCH_DISABLED"
    assert "plan" not in result.outputs


def test_request_cannot_enable_disabled_collection():
    def forbidden(*args, **kwargs):
        pytest.fail("missing-source collection must not make HTTP calls")

    plan = StageInput({}, {"purpose": "missing_sources", "sources": []})
    result = collect.run({"plan": plan}, {"fetch_missing_sources": True}, Context(fetch=forbidden))
    assert result.issues[0]["code"] == "MISSING_SOURCE_FETCH_DISABLED"


def test_opt_in_only_emits_missing_source_plan():
    source = evidence()
    source.payload["documents"] = source.payload["documents"][:1]
    result = curate.run({"evidence": source}, {}, Context(config={"fetch_missing_sources": True}))
    assert result.outcome == "needs_input"
    assert result.outputs["plan"][1]["purpose"] == "missing_sources"
    assert result.outputs["plan"][1]["maximum_attempts"] == 3


def test_job_can_narrow_enabled_collection():
    source = evidence()
    source.payload["documents"] = source.payload["documents"][:1]
    result = curate.run(
        {"evidence": source},
        {"fetch_missing_sources": False},
        Context(config={"fetch_missing_sources": True}),
    )
    assert "plan" not in result.outputs


def test_verify_requires_source_and_actual_writer_context():
    supplied = stages()
    supplied["package"].payload.pop("sources")
    result = verify.run(supplied, {}, Context(config={"models": {"verifier": "different"}}))
    assert result.outcome == "needs_input"


def test_verify_rejects_same_actual_model_without_calling_ai():
    supplied = stages()
    provider = Provider()
    with pytest.raises(ProtocolError, match="AI_MODELS_MUST_BE_DISTINCT"):
        verify.run(
            supplied, {}, Context(config={"models": {"verifier": "writer-test"}}, provider=provider)
        )
    assert provider.calls == []


def test_assemble_rejects_stale_verification():
    supplied = stages()
    supplied["draft"].payload["draft"]["lead"] = "変更されたリードである。"
    with pytest.raises(ProtocolError, match="VERIFICATION_BINDING_MISMATCH"):
        assemble.run(supplied, {"producer_id": str(uuid4())}, Context())


def test_transport_rejects_hash_corruption_and_unsafe_paths():
    raw = bundle_bytes({"contract_type": "example"}, {"payload.json": b'{"ok":true}'})
    assert read_bundle(raw)[1]["payload.json"] == b'{"ok":true}'
    changed = raw.replace(b'{"ok":true}', b'{"ok":null}')
    with pytest.raises(ProtocolError):
        read_bundle(changed)
    for path in ("../a", "/a", "a\\b", "C:/a", "a//b"):
        with pytest.raises(ProtocolError, match="BUNDLE_PATH_INVALID"):
            bundle_bytes({}, {path: b"a"})


def test_json_rejects_duplicate_keys_and_nonfinite():
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e309}'):
        with pytest.raises(ProtocolError):
            load_json(raw)


def test_stage_result_cache_avoids_second_paid_call(tmp_path):
    supplied = package()
    bundle = tmp_path / "input.nwstage"
    write_stage(bundle, "ArticlePackageV1", supplied.payload)
    request = tmp_path / "request.json"
    request.write_bytes(
        canonical(
            {
                "schema_version": "1.0",
                "module": "write",
                "inputs": {"package": {"file": bundle.name, "sha256": digest(bundle.read_bytes())}},
                "parameters": {},
            }
        )
    )
    provider = Provider()
    ctx = Context(config={"models": {"writer": "writer-test"}}, provider=provider)
    first = execute("write", request, tmp_path / "output", ctx)
    second = execute("write", request, tmp_path / "output", ctx)
    assert first == second and first["outcome"] == "success"
    assert provider.calls == ["writer-test"]


def test_os_lock_cannot_be_stolen_by_second_worker(tmp_path):
    with process_lock(tmp_path / "worker.lock"):
        with pytest.raises(ProtocolError, match="WORKER_BUSY"):
            with process_lock(tmp_path / "worker.lock"):
                pytest.fail("second worker acquired lock")


def test_verifier_rejects_forged_source_anchor_before_ai():
    inputs = stages()
    inputs["package"].payload["sources"][0]["body"] = "unrelated original source"
    provider = Provider()
    with pytest.raises(ProtocolError, match="FACT_EVIDENCE_MISMATCH"):
        verify.run(
            {"package": inputs["package"], "draft": inputs["draft"]},
            {},
            Context(config={"models": {"verifier": "verifier-test"}}, provider=provider),
        )
    assert provider.calls == []


def test_normal_explicit_collection_remains_available_with_missing_fetch_disabled():
    from datetime import UTC, datetime
    from pathlib import Path

    from app.modules.acquisition.http import FetchResponse
    from app.sources.config import load_sources
    from tests.unit.test_acquisition_service import RSS

    source = load_sources(Path("config/sources.example.yaml")).sources[0]
    source.legal.terms_reviewed_at = datetime.now(UTC)
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return FetchResponse(
            url, url, 200, {"content-type": "application/rss+xml"}, RSS, datetime.now(UTC)
        )

    result = collect.run(
        {
            "plan": StageInput(
                {}, {"purpose": "explicit", "sources": [source.model_dump(mode="json")]}
            )
        },
        {},
        Context(fetch=fetch),
    )
    assert result.outcome == "success" and len(calls) == 1
    assert len(result.outputs["sources"][1]["documents"]) == 1


def test_missing_image_credentials_never_call_remote_provider(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    with pytest.raises(ProtocolError, match="AI_IMAGE_CREDENTIAL_REQUIRED"):
        illustrate.run(
            {"draft": stages()["draft"]}, {}, Context(config={"models": {"image": "fixture"}})
        )
