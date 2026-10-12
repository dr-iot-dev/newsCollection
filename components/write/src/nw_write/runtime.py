"""One file-in/file-out interface for all independently packaged stages."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .common import Context, StageInput
from .protocol import (
    ProtocolError,
    atomic_write,
    canonical,
    digest,
    load_json,
    object_hash,
    process_lock,
    read_stage,
    require_local,
    write_stage,
)

MODULES = ("collect", "ground", "curate", "write", "verify", "illustrate", "assemble")
EXIT_CODES = {"success": 0, "needs_input": 10, "rejected": 20, "error": 30}
INPUT_CONTRACTS = {
    "collect": {"plan": "FetchPlanV1"},
    "ground": {"sources": "SourceBatchV1", "baseline": "EvidenceBatchV1"},
    "curate": {"evidence": "EvidenceBatchV1", "corpus": "EvidenceBatchV1"},
    "write": {"package": "ArticlePackageV1", "writing": "WritingOutputV1"},
    "verify": {"package": "ArticlePackageV1", "draft": "ArticleDraftV1"},
    "illustrate": {"draft": "ArticleDraftV1", "asset": "ImageAssetV1"},
    "assemble": {
        "package": "ArticlePackageV1",
        "draft": "ArticleDraftV1",
        "verification": "VerificationReportV1",
        "image": "ImageAssetV1",
        "approval": "ApprovalRecordV1",
    },
}


def _cached_result(cached: dict[str, Any]) -> dict[str, Any]:
    for record in cached["outputs"].values():
        path = Path(record["file"])
        if not path.exists() or digest(path.read_bytes()) != record["sha256"]:
            raise ProtocolError("CACHED_RESULT_CORRUPT")
    return cached


def execute(
    module: str, request_path: Path, output_dir: Path, context: Context | None = None
) -> dict[str, Any]:
    context = context or Context()
    root = request_path.resolve().parent
    if request_path.stat().st_size > 256 * 1024:
        raise ProtocolError("REQUEST_TOO_LARGE")
    request = load_json(request_path.read_bytes())
    if request.get("schema_version") != "1.0" or request.get("module") != module:
        raise ProtocolError("REQUEST_SCHEMA_OR_MODULE_INVALID")
    if set(request) - {"schema_version", "module", "inputs", "parameters"}:
        raise ProtocolError("REQUEST_UNKNOWN_FIELD")
    if module not in MODULES or not isinstance(request.get("inputs"), dict):
        raise ProtocolError("REQUEST_INPUTS_INVALID")
    parameters = request.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ProtocolError("REQUEST_PARAMETERS_INVALID")
    inputs = {}
    hashes = {}
    for role, record in request["inputs"].items():
        if not isinstance(record, dict) or set(record) != {"file", "sha256"}:
            raise ProtocolError("REQUEST_INPUT_REFERENCE_INVALID")
        from .protocol import relative_name

        relative_name(record["file"])
        path = (root / record["file"]).resolve()
        if not path.is_relative_to(root):
            raise ProtocolError("REQUEST_PATH_OUTSIDE_INPUT_ROOT")
        value = path.read_bytes()
        if record["sha256"] != digest(value):
            raise ProtocolError("REQUEST_INPUT_HASH_MISMATCH")
        if role not in INPUT_CONTRACTS[module]:
            raise ProtocolError("REQUEST_INPUT_ROLE_UNKNOWN")
        meta, payload, assets = read_stage(value, INPUT_CONTRACTS[module][role])
        inputs[role] = StageInput(meta, payload, assets)
        hashes[role] = record["sha256"]
    safe_config = {
        k: v
        for k, v in context.config.items()
        if not any(word in k.lower() for word in ("key", "password", "secret", "token"))
    }
    job_key = object_hash(
        {
            "module": module,
            "version": "1.0",
            "inputs": hashes,
            "parameters": parameters,
            "config": safe_config,
        }
    )
    output_dir = require_local(output_dir)
    work = output_dir / job_key[7:]
    with process_lock(output_dir / ".locks" / (job_key[7:] + ".lock")):
        result_path = work / "result.json"
        if result_path.exists():
            cached = load_json(result_path.read_bytes())
            retry_local_precondition = (
                cached.get("outcome") == "error"
                and not cached.get("outputs")
                and not cached.get("provenance", {}).get("records")
                and cached.get("issues", [{}])[0].get("code")
                in {"AI_CREDENTIAL_REQUIRED", "AI_IMAGE_CREDENTIAL_REQUIRED", "AI_MODEL_REQUIRED"}
            )
            if retry_local_precondition:
                result_path.unlink()
                (work / "intent.json").unlink(missing_ok=True)
            else:
                return _cached_result(cached)
        work.mkdir(parents=True, exist_ok=True)
        intent_path = work / "intent.json"
        if intent_path.exists():
            # A prior process may have paid for an AI call before it died.
            raise ProtocolError("PREVIOUS_STAGE_ATTEMPT_UNCERTAIN")
        atomic_write(
            intent_path,
            canonical({"job_key": job_key, "created_at": datetime.now(UTC).isoformat()}),
        )
        try:
            handler = importlib.import_module(f"{__package__}.handlers.{module}")
            outcome = handler.run(inputs, parameters, context)
            records = {}
            for role, (kind, payload, assets) in outcome.outputs.items():
                if kind == "DraftBundleV1":
                    raw = assets["bundle.nwdraft"]
                    path = work / (digest(raw)[7:] + ".nwdraft")
                    atomic_write(path, raw, immutable=True)
                    content_hash = digest(raw)
                else:
                    path = work / (role + ".nwstage")
                    content_hash = write_stage(
                        path,
                        kind,
                        payload,
                        assets,
                        {
                            "module": module,
                            "version": "1.0",
                            "job_key": job_key,
                            "records": context.records,
                            "input_hashes": hashes,
                        },
                    )
                records[role] = {"file": str(path), "sha256": content_hash}
            result = {
                "schema_version": "1.0",
                "job_key": job_key,
                "outcome": outcome.outcome,
                "outputs": records,
                "issues": outcome.issues,
                "provenance": {
                    "module": module,
                    "input_hashes": hashes,
                    "fetch_missing_sources": context.allow_fetch(parameters),
                    "records": context.records,
                },
            }
        except Exception as exc:
            result = {
                "schema_version": "1.0",
                "job_key": job_key,
                "outcome": "error",
                "outputs": {},
                "issues": [{"code": getattr(exc, "code", "STAGE_FAILED"), "retryable": False}],
                "provenance": {
                    "module": module,
                    "input_hashes": hashes,
                    "records": context.records,
                },
            }
        atomic_write(result_path, canonical(result), immutable=True)
        return result


def main(module: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nw-stage" if module is None else "nw-" + module)
    if module is None:
        parser.add_argument("module", choices=MODULES)
    parser.add_argument("operation", choices=["run"])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--fetch-missing-sources", action=argparse.BooleanOptionalAction, default=None
    )
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text()) if args.config else {}
    if "FETCH_MISSING_SOURCES" in os.environ:
        value = os.environ["FETCH_MISSING_SOURCES"].lower()
        if value not in {"true", "false", "1", "0"}:
            parser.error("FETCH_MISSING_SOURCES must be a boolean")
        config["fetch_missing_sources"] = value in {"true", "1"}
    if args.fetch_missing_sources is not None:
        config["fetch_missing_sources"] = args.fetch_missing_sources
    config.setdefault("fetch_missing_sources", False)
    try:
        result = execute(module or args.module, args.request, args.output, Context(config=config))
        print(json.dumps(result, ensure_ascii=False))
        return EXIT_CODES[result["outcome"]]
    except (ProtocolError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "job_key": None,
                    "outcome": "error",
                    "outputs": {},
                    "provenance": {"module": module or args.module},
                    "issues": [
                        {"code": getattr(exc, "code", "STAGE_INPUT_FAILED"), "retryable": False}
                    ],
                }
            )
        )
        return 30


if __name__ == "__main__":
    raise SystemExit(main())
