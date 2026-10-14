# ruff: noqa: RUF001
"""Evaluate five existing comparisons separately with the current document instructions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/comparison-A-individual-first5-20261014"
INSTRUCTIONS = ROOT / "docs/comparison-A-instructions-20261014.md"
SAVED = ROOT / ".local/comparison-generate-then-evaluate-experiment-20261014-v2"
MODEL = "gpt-4.1-2025-04-14"
VERSION = "comparison-A-individual-absolute-score-v1"
CLUSTERS = ["C10", "C13", "C22", "C24", "C02"]
PATHS = [
    "comparison-article-c10-robot-vacuums-20261014.md",
    "comparison-article-c13-property-entry-20261014.md",
    "comparison-article-c22-ai-interviews-20261014.md",
    "comparison-article-c24-document-entry-20261014.md",
    "comparison-article-c02-equipment-monitoring-20261014.md",
]
STATUS = {"eligible": "適切", "ineligible": "不適", "needs_confirmation": "要確認"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def save(name, value):
    path = OUT / name
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != data:
            raise RuntimeError("IMMUTABLE_OUTPUT_CONFLICT: " + name)
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(data)


def api_key():
    key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if key:
        return key
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(("AI_API_KEY=", "OPENAI_API_KEY=")):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise RuntimeError("API_KEY_UNAVAILABLE")


def current_prompt():
    document = INSTRUCTIONS.read_text(encoding="utf-8-sig")
    return (
        document.split("## 修正した指示", 1)[1].split("```text\n", 1)[1].split("```", 1)[0].strip()
    )


def prepare():
    prompt = current_prompt()
    original = read(SAVED / "legacy-documents.json")[:5]
    documents = []
    for cluster, file, source in zip(CLUSTERS, PATHS, original, strict=True):
        path = ROOT / "docs" / file
        markdown = path.read_text(encoding="utf-8")
        assert markdown == source["article_markdown"], "ARTICLE_SNAPSHOT_CHANGED"
        assert len(source["sources"]) == 3
        for release in source["sources"]:
            assert digest(release["text"]) == release["input_hash"]
        documents.append(
            {
                "id": source["id"],
                "cluster": cluster,
                "article_path": path.as_posix(),
                "article_hash": digest(markdown),
                "article_markdown": markdown,
                "source_article_ids": source["source_article_ids"],
                "sources": source["sources"],
                "generation_record": source["generation_record"],
            }
        )
    save(
        "instructions.json", {"version": VERSION, "instructions": prompt, "sha256": digest(prompt)}
    )
    save("documents.json", documents)
    save(
        "policy.json",
        {
            "version": VERSION,
            "model": MODEL,
            "generator_model": "gpt-4.1-mini-2025-04-14",
            "selection": "First five original editorial candidates, fixed before evaluation",
            "calls": 5,
            "articles_per_call": 1,
            "sources_per_call": 3,
            "sources_full_text": True,
            "previous_scores_supplied": False,
            "previous_verdicts_supplied": False,
            "extracted_facts_supplied": False,
            "pair_checks": False,
            "twelve_check_gate": False,
            "score": "absolute 0-100, for every status, no adoption threshold",
            "semantic_post_filter": False,
            "article_rewrite": False,
            "wordpress_write": False,
        },
    )
    print("prepared five articles / fifteen complete releases", flush=True)


def response_schema(article_id):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "status", "score", "reason"],
        "properties": {
            "id": {"type": "string", "enum": [article_id]},
            "status": {"type": "string", "enum": list(STATUS)},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "reason": {"type": "string", "minLength": 1},
        },
    }


def validate_output(value, article_id):
    assert set(value) == {"id", "status", "score", "reason"}
    assert value["id"] == article_id and value["status"] in STATUS
    assert type(value["score"]) is int and 0 <= value["score"] <= 100
    assert isinstance(value["reason"], str) and value["reason"].strip()


def evaluate():
    documents = read(OUT / "documents.json")
    prompt = read(OUT / "instructions.json")["instructions"]
    assert prompt == current_prompt(), "INSTRUCTIONS_CHANGED_AFTER_PREPARATION"
    results = []
    for document in documents:
        article_id = document["id"]
        data = {
            "article": {
                "id": article_id,
                "article_markdown": document["article_markdown"],
                "generation_record": document["generation_record"],
            },
            "sources": document["sources"],
        }
        payload = {
            "model": MODEL,
            "instructions": prompt,
            "input": canonical(data),
            "store": False,
            "temperature": 0,
            "max_output_tokens": 2400,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "individual_comparison_evaluation",
                    "strict": True,
                    "schema": response_schema(article_id),
                }
            },
        }
        uid = digest(canonical(payload))
        save("requests/" + uid + ".json", payload)
        response_path = OUT / "responses" / (uid + ".json")
        if response_path.exists():
            raw = read(response_path)
        else:
            intent_name = "intents/" + uid + ".json"
            if (OUT / intent_name).exists():
                raise RuntimeError("REQUEST_OUTCOME_UNKNOWN: no blind repeat for " + article_id)
            save(intent_name, {"id": article_id, "sent_at": datetime.now(UTC).isoformat()})
            print("evaluating", document["cluster"], article_id, flush=True)
            with httpx.Client(
                trust_env=False, follow_redirects=False, timeout=httpx.Timeout(240, connect=15)
            ) as client:
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    json=payload,
                    headers={"Authorization": "Bearer " + api_key()},
                )
            raw = response.json()
            save("responses/" + uid + ".json", raw)
            if response.status_code != 200:
                raise RuntimeError(
                    "API_HTTP_"
                    + str(response.status_code)
                    + ":"
                    + str(raw.get("error", {}).get("code"))
                )
        if raw.get("status") != "completed":
            raise RuntimeError("INCOMPLETE_RESPONSE: " + article_id)
        assert raw["model"] == MODEL
        text = "".join(
            item.get("text", "")
            for output in raw["output"]
            if output["type"] == "message"
            for item in output["content"]
            if item["type"] == "output_text"
        )
        value = json.loads(text)
        validate_output(value, article_id)
        result = {
            "cluster": document["cluster"],
            "article_path": document["article_path"],
            "article_hash": document["article_hash"],
            "request_sha256": uid,
            "response_id": raw["id"],
            "model": raw["model"],
            "usage": raw["usage"],
            "output": value,
        }
        save("results/" + article_id + ".json", result)
        results.append(result)
        print(
            document["cluster"],
            STATUS[value["status"]],
            value["score"],
            value["reason"],
            flush=True,
        )
    save("results.json", results)
    validation = {
        "articles": len(results),
        "independent_requests": len(results),
        "one_article_and_three_full_sources_per_request": True,
        "output_schema_valid": True,
        "other_article_or_previous_results_supplied": False,
        "semantic_post_filter": False,
        "original_files_unchanged": all(
            digest(Path(d["article_path"]).read_text(encoding="utf-8")) == d["article_hash"]
            and all(digest(s["text"]) == s["input_hash"] for s in d["sources"])
            for d in documents
        ),
        "negative_or_borderline_detection_measured": False,
        "wordPress_requests": 0,
    }
    assert validation["articles"] == 5 and validation["original_files_unchanged"]
    for d, result in zip(documents, results, strict=True):
        request = read(OUT / "requests" / (result["request_sha256"] + ".json"))
        supplied = json.loads(request["input"])
        assert set(supplied) == {"article", "sources"}
        assert supplied["article"]["id"] == d["id"]
        assert supplied["article"]["article_markdown"] == d["article_markdown"]
        assert supplied["sources"] == d["sources"]
    save("validation.json", validation)
    report = [
        "# 個別比較記事の評価：第1〜第5候補",
        "",
        "実施日：2026-10-14。ユーザー指定の修正指示に絶対評価スコアを追加し、保存済み完成記事5本を1本ずつ評価した。",
        "",
        "モデル：gpt-4.1-2025-04-14（生成時はgpt-4.1-mini-2025-04-14）。temperature=0。原資料15件の全文を再利用し、以前の点数・合否・facts抜粋・他記事は入力していない。本文は修正していない。",
        "",
        "## 実際に送った指示",
        "",
        "```text",
        prompt,
        "```",
        "",
        "## モデルの結果",
        "",
        "|クラスター|記事|判定|絶対評価点|",
        "|---|---|---|---:|",
    ]
    for result in results:
        value = result["output"]
        title = next(
            d["article_markdown"].splitlines()[0][2:] for d in documents if d["id"] == value["id"]
        )
        report.append(f"|{result['cluster']}|{title}|{STATUS[value['status']]}|{value['score']}|")
    for result in results:
        value = result["output"]
        report.extend(
            [
                "",
                "### " + result["cluster"],
                "",
                value["reason"],
                "",
                "原稿：[記事](" + result["article_path"] + ")",
            ]
        )
    report.extend(
        [
            "",
            "## 動作確認と限界",
            "",
            "5回の各要求は記事1本・対応する原資料3件だけを含み、同じ指示を使用した。5結果はid/status/score/reasonだけの形式で、全件に0〜100の整数スコアと理由がある。12項目や全ペアの合否集計、後段の意味的な採否変更は行っていない。原稿と原資料の一致を確認した。",
            "",
            "今回の5本は以前に編集された完成記事で、意図的な誤り・完全複製・既知不適を含めた性能試験ではない。この5本だけでは不適を確実に除外する性能や採点の再現性は確定しない。別記事は入力していないため、今回の各スコアは記事間の順位調整によるものではない。",
            "",
            "保存ログ：[要求・応答・結果](../.local/comparison-A-individual-first5-20261014/)。使用量はresults.json、入力・出力の形式確認はvalidation.jsonを参照。WordPress投稿は0回。残りのクラスターは評価していない。",
        ]
    )
    (ROOT / "docs/comparison-A-individual-first5-results-20261014.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    print("completed five independent evaluations", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "evaluate"])
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare()
    else:
        evaluate()


if __name__ == "__main__":
    main()
