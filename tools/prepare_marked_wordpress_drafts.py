# ruff: noqa: E402, E501
"""Prepare -> one A evaluation -> WPuploader files, reusing cached successful calls."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nw_generation.marked_comparison import (
    POLICY,
    PROMPT,
    assessment_results,
    catalog,
    claim_units,
    export_bundle,
    prepare_document,
    schema,
    validate_schema,
)
from nw_generation.protocol import atomic_write, canonical, digest, object_hash
from tools import reevaluate_marked_comparisons as prior

OUT = ROOT / ".local/comparison-A-wordpress-20261014-v7"
SAVED = ROOT / ".local/comparison-generation-marked-reevaluation-20261014-v3-2"
TITLES = {
    "H008-1": "業界別データ活用プラットフォームの用途と導入形態",
    "H012-0": "健康管理サービスの支援方法と計測・データ共有の違い",
    "H015-0": "企業ITのネットワーク・ブラウザ・データ基盤の役割",
    "H020-0": "共同農園・わさび栽培設備・家庭向けアプリの用途",
    "H023-0": "住宅IoTの導入方式と居住者向け機能・運用の違い",
    "H029-0": "企画支援・メディア計画・ナレッジ管理のAIサービス",
    "H030-0": "医療AIの院内業務・予約対応・安全実行基盤の役割",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(name, value, immutable=False):
    atomic_write(OUT / name, canonical(value), immutable=immutable)


def prepare():
    manifest = {r["id"]: r for r in read(SAVED / "input-manifest.json")}
    docs = []
    for d in read(SAVED / "documents.json"):
        h = manifest[d["id"]]["original_generation_request"]
        run = read(prior.PRIOR / "calls" / (h + ".json"))
        assert run["output"]["article_markdown"] == d["article_markdown"]
        writer = {"model": run["model"], "response_id": run["response_id"], "request_sha256": h}
        ready = prepare_document(d, TITLES[d["id"]], writer)
        ready = editorial_revision(ready)
        docs.append(ready)
        atomic_write(
            OUT / "prepared" / (d["id"] + ".md"),
            ("# " + ready["title"] + "\n\n" + ready["markdown"]).encode(),
            immutable=True,
        )
    save("prepared-documents.json", docs, True)
    save("rubric.json", read(SAVED / "rubric.json"), True)
    save(
        "policy.json",
        {
            "version": POLICY,
            "selected_method": "A",
            "evaluation_calls_per_batch": 1,
            "shared_fact_pass_supplied": False,
            "extra_semantic_review": False,
            "original_generation_marks_retained": True,
            "original_common_exclusions_retained": True,
            "semantic_authority": "A comparison gates and 12 editorial checks only",
            "output": ".nwdraft for WPuploader",
            "image_enabled": False,
            "remote_upload_performed": False,
            "evaluator_model": EVALUATOR_MODEL,
            "reasoning_effort": "medium",
        },
        True,
    )
    save("prompt.json", {"instructions": PROMPT}, True)
    save("original-exclusions.json", read(SAVED / "blocked-by-original-marks.json"), True)
    print(
        "prepared", len(docs), "static errors", [(d["id"], d["deterministic_checks"]) for d in docs]
    )


def editorial_revision(d):
    revisions = {
        "H012-0": {
            "lead": "健康支援を企画する担当者が、利用者にどの支援方法を案内するかを検討するため、イオン「からサポ」、ミルウス「MIRUWSⓇ M4」、ネットウエルシステム「WWS」を整理する。行動支援、継続計測・データ共有、短時間の状態把握という役割と、取得方法・対象利用者・提供条件の違いを比べる。",
            "question": "利用者に案内する支援方法を選ぶ際は、食事・運動の行動支援、継続的なデータ計測と共有、短時間のセルフチェックのどこを支えるかを先に確認する。からサポの食事・運動支援、MIRUWSⓇ M4の計測・PDS機能、WWSの顔画像解析という違いは、この役割を整理する判断材料である。料金と提供時期は各資料の記載範囲で確認する。",
        },
        "H023-0": {
            "lead": "住宅IoTの採用範囲を設計する住宅事業者向けに、長谷工コーポレーション・LiveSmart、Gハウス・リンクジャパン、南部建設・アクセルラボの取り組みを整理する。物件形態、居住者の操作方法、機器への対応、運営支援の範囲を比べ、計画する住宅で何を確認するかを明確にする。",
            "question": "住宅IoTを仕様に組み込む際は、対象物件と居住者向け機能、導入時の機器設定、運営側の管理機能を確認する。長谷工の事例は住民アプリの遠隔操作と環境確認、Gハウスの事例は注文住宅への標準搭載、南部建設の事例は賃貸物件の家電操作と管理支援を示す。異なる物件種別の事例から、採用範囲や必要な確認事項を整理するための比較である。導入効果は各社の個別事例として読む。",
        },
        "H030-0": {
            "lead": "医療機関のDX担当者が、院内記録・事務、患者予約、AI実行統制のどこに仕組みを置くかを検討するため、「Apollo AI」「Galapagos」「MediLine Engine」の役割と提供段階を比べる。対象業務、既存システムとの関係、公表された導入事例や予定を整理する。",
            "question": "医療AIの導入範囲を検討する際は、院内記録・事務の支援、患者予約の対応、AI機能の実行統制という役割を区別する。Apollo AIは電子カルテ連携、GalapagosはLINEを使う予約対応、MediLine Engineは制約・検証・監査を伴う実行基盤として説明されている。各資料の導入例と提供予定を確認し、既存システムとの接続や権限管理で何を確かめるかを整理する。",
        },
    }
    if d["id"] not in revisions:
        return d
    revision = revisions[d["id"]]
    import re

    body = d["body"]
    body = re.sub(r"\n## リード(?:文)?\n.*?(?=\n---|\n\|)", "", body, count=1, flags=re.S)
    body = body.replace("未記載", "資料で確認できず").replace("明示なし", "資料で確認できず")
    body = body.replace("## 考察", "## 比較の考察")
    if d["id"] == "H030-0":
        body = body.replace(
            "AIの安全利用を制度的に担保", "制約・実行統制・検証・監査に基づくAI利用の設計"
        )
        body = body.replace(
            "医療AIの信頼性と安全性を確保する", "AIの実行権限と安全制約を管理する設計を示している"
        )
        body = body.replace(
            "約95%の高い定着率を誇り", "提供元の発表では永井病院での現場定着率が約95%とされ"
        )
        body = body.replace("約95%の高い現場定着率", "永井病院での現場定着率は約95%との発表")
        body = body.replace(
            "退院サマリ作成時間37分→3分に短縮", "永井病院の事例で退院サマリ作成時間37分→3分との報告"
        )
    head, sources = body.split("\n## 出典\n", 1)
    head = re.sub(r"\n(?:以上、|以上の比較により、).*", "", head, flags=re.S).rstrip()
    body = head + "\n\n## 導入時に確認する点\n\n" + revision["question"] + "\n\n## 出典\n" + sources
    d = dict(d)
    d.update(
        lead=revision["lead"],
        body=body,
        markdown=revision["lead"] + "\n\n" + body + "\n",
        editorial_revision={
            "editor": "Codex",
            "model_name": None,
            "changes": [
                "specific reader question",
                "remove ungrounded market generalization",
                "source-scoped unknown labels",
                "role/condition explanation",
                "narrow medical safety claims where applicable",
            ],
        },
    )
    d["draft_hash"] = object_hash({"title": d["title"], "markdown": d["markdown"]})
    from nw_generation.marked_comparison import format_errors

    d["deterministic_checks"] = format_errors(d)
    return d


EVALUATOR_MODEL = "gpt-5.2-2025-12-11"


def call_once(data, output_schema):
    payload = {
        "model": EVALUATOR_MODEL,
        "instructions": PROMPT,
        "input": canonical(data).decode(),
        "store": False,
        "reasoning": {"effort": "medium"},
        "max_output_tokens": 64000,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "marked_comparison_A",
                "strict": True,
                "schema": output_schema,
            }
        },
    }
    spec = {"tag": "A:wordpress:1", "version": POLICY, "payload": payload}
    h = object_hash(spec)[7:]
    path = OUT / "calls" / (h + ".json")
    if path.exists():
        r = read(path)
        validate_schema(r["output"], output_schema)
        return r
    save("requests/" + h + ".json", spec, True)
    response_path = OUT / "responses" / (h + ".json")
    if response_path.exists():
        raw = read(response_path)
    else:
        intent = OUT / "intents" / (h + ".json")
        if intent.exists():
            raise RuntimeError(
                "API_REQUEST_OUTCOME_UNKNOWN: do not repeat a potentially completed request"
            )
        save(
            "intents/" + h + ".json",
            {"request_sha256": h, "sent_at": datetime.now(UTC).isoformat()},
            True,
        )
        with httpx.Client(
            trust_env=False, follow_redirects=False, timeout=httpx.Timeout(600, connect=10)
        ) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                json=payload,
                headers={"Authorization": "Bearer " + prior.base.apikey()},
            )
        raw = response.json()
        save("responses/" + h + ".json", raw, True)
        if response.status_code != 200:
            raise RuntimeError(
                "API_HTTP_"
                + str(response.status_code)
                + ":"
                + str(raw.get("error", {}).get("code"))
            )
    if raw.get("status") != "completed":
        raise RuntimeError("API_RESPONSE_INCOMPLETE")
    assert raw["model"] == EVALUATOR_MODEL
    text = "".join(
        c.get("text", "")
        for o in raw.get("output", [])
        if o.get("type") == "message"
        for c in o.get("content", [])
        if c.get("type") == "output_text"
    )
    output = json.loads(text)
    validate_schema(output, output_schema)
    u = raw["usage"]
    cached = u.get("input_tokens_details", {}).get("cached_tokens", 0)
    cost = ((u["input_tokens"] - cached) * 1.75 + cached * 0.175 + u["output_tokens"] * 14) / 1e6
    r = {
        "tag": "A:wordpress:1",
        "model": raw["model"],
        "request_sha256": h,
        "response_id": raw["id"],
        "raw_output": output,
        "output": output,
        "usage": u,
        "estimated_usd": cost,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    save("calls/" + h + ".json", r, True)
    print("completed one A call", r["model"], "USD", round(cost, 6), flush=True)
    return r


def evaluate():
    docs = read(OUT / "prepared-documents.json")
    payload = {
        "articles": [
            {
                k: d[k]
                for k in [
                    "id",
                    "title",
                    "markdown",
                    "source_article_ids",
                    "sources",
                    "deterministic_checks",
                    "draft_hash",
                    "package_hash",
                ]
            }
            | {
                "claim_units": claim_units(d),
                "generation_mark": {
                    k: d["generation_history"][k] for k in ["comparison_status", "issues"]
                },
            }
            for d in docs
        ],
        "rubric": read(OUT / "rubric.json"),
        "exact_evidence_catalog": catalog(docs),
    }
    r = call_once(payload, schema(docs, read(OUT / "rubric.json")))
    results = assessment_results(docs, r["output"])
    save(
        "assessment.json",
        {
            "request_sha256": r["request_sha256"],
            "input_hash": object_hash(payload),
            "results": results,
            "pair_checks": r["output"]["pair_checks"],
            "estimated_usd": r["estimated_usd"],
        },
    )
    print(
        "A result",
        [(r["id"], r["comparison_status"], r["ready"], r["technical_errors"]) for r in results],
    )


def export():
    docs = {d["id"]: d for d in read(OUT / "prepared-documents.json")}
    evaluation = read(OUT / "assessment.json")
    call = read(OUT / "calls" / (evaluation["request_sha256"] + ".json"))
    actual = assessment_results(list(docs.values()), call["output"])
    assert actual == evaluation["results"]
    request = read(OUT / "requests" / (call["request_sha256"] + ".json"))["payload"]
    supplied = json.loads(request["input"])["articles"]
    assert {a["id"] for a in supplied} == set(docs)
    for a in supplied:
        d = docs[a["id"]]
        assert a["draft_hash"] == d["draft_hash"] and a["markdown"] == d["markdown"]
        assert a["package_hash"] == d["package_hash"] and a["sources"] == d["sources"]
    files = []
    for r in actual:
        if not r["ready"]:
            continue
        path = export_bundle(docs[r["id"]], r, call, OUT / "ready")
        files.append(
            {
                "id": r["id"],
                "path": str(path),
                "sha256": digest(path.read_bytes()),
                "A_score": r["normal_score"],
            }
        )
    save(
        "handoff.json",
        {
            "selected_method": "A",
            "policy": POLICY,
            "source_evaluation_request": call["request_sha256"],
            "drafts": files,
            "blocked": [r for r in actual if not r["ready"]],
            "remote_upload_performed": False,
            "evaluator_model": EVALUATOR_MODEL,
            "reasoning_effort": "medium",
        },
    )
    print("handoff files", [(r["id"], r["path"]) for r in files])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "evaluate", "export"])
    args = parser.parse_args()
    globals()[args.stage]()


if __name__ == "__main__":
    main()
