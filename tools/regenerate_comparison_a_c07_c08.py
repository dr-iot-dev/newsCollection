# ruff: noqa: E402, RUF001
"""Regenerate C07/C08 and preserve negative declarations through individual verification."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import evaluate_comparison_a_individual as base

OUT = ROOT / ".local/comparison-A-regenerated-c07-c08-20261014-v3"
base.OUT = OUT
WM = "gpt-4.1-mini-2025-04-14"
GENERATION_DOC = ROOT / "docs/comparison-generation-instructions-20261014.md"
SOURCE_DOCS = ROOT / ".local/comparison-A-individual-all30-20261014/documents.json"
REPORT = ROOT / "docs/comparison-A-regenerated-c07-c08-results-20261014.md"


def prompt_from_document(path):
    return path.read_text(encoding="utf-8-sig").split("```text\n", 1)[1].split("```", 1)[0].strip()


def body_mark(markdown):
    first = markdown.lstrip().splitlines()[0].strip()
    title = re.sub(r"^#+\s*", "", first).strip()
    if title == "比較不適（公開不可）":
        return "ineligible"
    if title == "要確認（公開不可）":
        return "needs_confirmation"
    return None


def effective_status(generated, verification):
    mark = body_mark(generated["article_markdown"])
    if mark == "ineligible" or generated["status"] == "ineligible":
        return "ineligible"
    if generated["status"] == "needs_confirmation" or mark == "needs_confirmation":
        return "ineligible" if verification["status"] == "ineligible" else "needs_confirmation"
    return verification["status"]


def generation_schema(article_id):
    schema = base.response_schema(article_id)
    schema["properties"].pop("score")
    schema["properties"]["article_markdown"] = {"type": "string", "minLength": 1}
    schema["required"] = list(schema["properties"])
    return schema


def call(stage, article_id, model, instructions, data, schema, limit):
    payload = {
        "model": model,
        "instructions": instructions,
        "input": base.canonical(data),
        "store": False,
        "temperature": 0,
        "max_output_tokens": limit,
        "text": {
            "format": {"type": "json_schema", "name": stage, "strict": True, "schema": schema}
        },
    }
    uid = base.digest(base.canonical(payload))
    base.save("requests/" + uid + ".json", payload)
    response_path = OUT / "responses" / (uid + ".json")
    if response_path.exists():
        raw = base.read(response_path)
    else:
        intent = "intents/" + uid + ".json"
        if (OUT / intent).exists():
            raise RuntimeError("REQUEST_OUTCOME_UNKNOWN: no blind repeat")
        base.save(
            intent, {"stage": stage, "id": article_id, "sent_at": datetime.now(UTC).isoformat()}
        )
        print(stage, article_id, flush=True)
        with httpx.Client(
            trust_env=False, follow_redirects=False, timeout=httpx.Timeout(240, connect=15)
        ) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                json=payload,
                headers={"Authorization": "Bearer " + base.api_key()},
            )
        raw = response.json()
        base.save("responses/" + uid + ".json", raw)
        if response.status_code != 200:
            raise RuntimeError(
                f"API_HTTP_{response.status_code}:{(raw.get('error') or {}).get('code')}"
            )
    assert raw.get("status") == "completed" and raw["model"] == model
    text = "".join(
        c.get("text", "")
        for o in raw["output"]
        if o["type"] == "message"
        for c in o["content"]
        if c["type"] == "output_text"
    )
    value = json.loads(text)
    assert set(value) == set(schema["properties"])
    assert value["id"] == article_id and value["status"] in base.STATUS
    assert value["reason"].strip()
    if stage == "individual_verification":
        base.validate_output(value, article_id)
    else:
        assert value["article_markdown"].strip()
    receipt = {
        "stage": stage,
        "request_sha256": uid,
        "response_id": raw["id"],
        "model": raw["model"],
        "usage": raw["usage"],
        "output": value,
    }
    base.save("calls/" + uid + ".json", receipt)
    return receipt


def prepare():
    sources = [d for d in base.read(SOURCE_DOCS) if d["cluster"] in ["C07", "C08"]]
    assert len(sources) == 2
    records = []
    for document in sources:
        for source in document["sources"]:
            assert base.digest(source["text"]) == source["input_hash"]
        records.append(
            {
                "id": document["cluster"] + "-regenerated",
                "cluster": document["cluster"],
                "sources": document["sources"],
                "original_article_id": document["id"],
            }
        )
    base.save("source-records.json", records)
    base.save(
        "prompts.json",
        {"generation": prompt_from_document(GENERATION_DOC), "verification": base.current_prompt()},
    )
    base.save(
        "policy.json",
        {
            "generator_model": WM,
            "verifier_model": base.MODEL,
            "same_original_three_sources": True,
            "old_article_or_known_verdict_supplied_to_generator": False,
            "per_article_verification": True,
            "negative_declaration_in_body_is_authoritative": True,
            "body_status_mapping_is_not_semantic_review": True,
            "output_score_is_absolute": True,
            "wordpress_write": False,
        },
    )
    simulated = {"status": "eligible", "article_markdown": "# 比較不適（公開不可）\n\n理由"}
    assert effective_status(simulated, {"status": "eligible"}) == "ineligible"
    assert body_mark("# 通常記事\n\n一部機能の不適な使用について") is None
    assert (
        effective_status(
            {"status": "needs_confirmation", "article_markdown": "# 要確認（公開不可）"},
            {"status": "eligible"},
        )
        == "needs_confirmation"
    )
    print("prepared two source sets; explicit negative body mark blocks adoption", flush=True)


def execute():
    prompts = base.read(OUT / "prompts.json")
    assert prompts["verification"] == base.current_prompt()
    assert prompts["generation"] == prompt_from_document(GENERATION_DOC)
    records = base.read(OUT / "source-records.json")
    results = []
    for record in records:
        generated_call = call(
            "comparison_generation",
            record["id"],
            WM,
            prompts["generation"],
            {"id": record["id"], "sources": record["sources"]},
            generation_schema(record["id"]),
            5000,
        )
        generated = generated_call["output"]
        if generated["status"] != "eligible":
            assert body_mark(generated["article_markdown"]) == generated["status"], (
                "NEGATIVE_BODY_MARK_MISSING"
            )
        else:
            assert body_mark(generated["article_markdown"]) is None, "BODY_STATUS_CONFLICT"
        path = OUT / "articles" / (record["cluster"] + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            assert path.read_text(encoding="utf-8") == generated["article_markdown"]
        else:
            path.write_text(generated["article_markdown"], encoding="utf-8")
        verification_call = call(
            "individual_verification",
            record["id"],
            base.MODEL,
            prompts["verification"],
            {
                "article": {
                    "id": record["id"],
                    "article_markdown": generated["article_markdown"],
                    "generation_record": {
                        "comparison_status": generated["status"],
                        "issues": []
                        if generated["status"] == "eligible"
                        else [generated["reason"]],
                    },
                },
                "sources": record["sources"],
            },
            base.response_schema(record["id"]),
            2400,
        )
        verification = verification_call["output"]
        result = {
            "cluster": record["cluster"],
            "article_path": path.as_posix(),
            "generation": generated_call,
            "verification": verification_call,
            "body_mark": body_mark(generated["article_markdown"]),
            "effective_status": effective_status(generated, verification),
            "score": verification["score"],
        }
        base.save("results/" + record["cluster"] + ".json", result)
        results.append(result)
        print(
            record["cluster"],
            "generation",
            generated["status"],
            "verification",
            verification["status"],
            "score",
            verification["score"],
            flush=True,
        )
    base.save("results.json", results)
    for record, result in zip(records, results, strict=True):
        assert (
            Path(result["article_path"]).read_text(encoding="utf-8")
            == result["generation"]["output"]["article_markdown"]
        )
        verify_request = base.read(
            OUT / "requests" / (result["verification"]["request_sha256"] + ".json")
        )
        data = json.loads(verify_request["input"])
        assert (
            data["article"]["article_markdown"]
            == result["generation"]["output"]["article_markdown"]
        )
        assert data["sources"] == record["sources"]
        if result["body_mark"] == "ineligible":
            assert result["effective_status"] == "ineligible"
    base.save(
        "validation.json",
        {
            "sources_unchanged": all(
                base.digest(s["text"]) == s["input_hash"] for r in records for s in r["sources"]
            ),
            "generated_and_verified_body_identical": True,
            "negative_generation_status_visible_in_body": True,
            "negative_body_mark_cannot_be_accepted": True,
            "raw_verifier_honors_negative_marks": all(
                r["body_mark"] != "ineligible"
                or r["verification"]["output"]["status"] == "ineligible"
                for r in results
            ),
            "one_article_per_verification": True,
            "wordpress_calls": 0,
        },
    )
    lines = [
        "# C07・C08の再生成と個別検証",
        "",
        (
            "実施日：2026-10-14。以前と同じ3件の原資料だけから再生成。"
            "GPT-4.1 miniで生成、GPT-4.1で1本ずつ検証した。"
            "以前の草稿・既知の正解は生成入力に渡していない。"
        ),
        "",
        "生成時に比較不適と判断した場合は本文先頭に『比較不適（公開不可）』と理由・対象資料を示す。不適表示は検証でも採用不可として有効にする。生成・検証の元応答と、表示に基づく最終状態を別々に保持した。",
        "",
        "|クラスター|生成時判定|本文の不適表示|検証モデル判定|絶対評価点|最終状態|",
        "|---|---|---|---|---:|---|",
    ]
    for r in results:
        g, v = r["generation"]["output"], r["verification"]["output"]
        mark = (
            "比較不適（公開不可）"
            if r["body_mark"] == "ineligible"
            else "要確認（公開不可）"
            if r["body_mark"]
            else "なし"
        )
        lines.append(
            f"|{r['cluster']}|{base.STATUS[g['status']]}|{mark}|{base.STATUS[v['status']]}|{v['score']}|{base.STATUS[r['effective_status']]}|"
        )
    for r in results:
        lines.extend(
            [
                "",
                "## " + r["cluster"],
                "",
                "再生成原稿：[本文](" + r["article_path"] + ")",
                "",
                "生成理由：" + r["generation"]["output"]["reason"],
                "",
                "検証理由：" + r["verification"]["output"]["reason"],
                "",
                "```markdown",
                r["generation"]["output"]["article_markdown"],
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## 保存と確認",
            "",
            "本文への不適表示はモデルが生成したもので、後から手動で付けていない。検証には保存した生成本文をそのまま渡した。本文の明示状態と生成記録を保持する機械処理は、意味の再判定を行わない。過去の28記事評価結果や元原稿は変更していない。WordPress投稿は行っていない。",
            "",
            "入力、要求・応答、生成結果、検証結果、状態の対応確認は[保存ログ](../.local/comparison-A-regenerated-c07-c08-20261014-v3/)に保存。指示は[生成指示](comparison-generation-instructions-20261014.md)と[個別検証指示](comparison-A-instructions-20261014.md)を参照。",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "execute"])
    if parser.parse_args().stage == "prepare":
        prepare()
    else:
        execute()


if __name__ == "__main__":
    main()
