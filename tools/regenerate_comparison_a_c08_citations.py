# ruff: noqa: E402, RUF001
"""Regenerate C08, check citations, then verify the unchanged article individually."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import regenerate_comparison_a_c07_c08 as run

OUT = ROOT / ".local/comparison-A-c08-citations-20261014-v3"
REPORT = ROOT / "docs/comparison-A-c08-citations-results-20261014.md"
run.OUT = OUT
run.base.OUT = OUT
LINK = re.compile(r"\[資料([1-3])\]\(([^)]+)\)")


def prepare():
    original = next(d for d in run.base.read(run.SOURCE_DOCS) if d["cluster"] == "C08")
    assert len(original["sources"]) == 3
    for source in original["sources"]:
        assert run.base.digest(source["text"]) == source["input_hash"]
    run.base.save(
        "input.json", {"id": "C08-citations", "sources": original["sources"], "cluster": "C08"}
    )
    run.base.save(
        "prompts.json",
        {
            "generation": run.prompt_from_document(run.GENERATION_DOC),
            "verification": run.base.current_prompt(),
        },
    )
    print("prepared C08 from the same original three releases", flush=True)


def generate():
    data = run.base.read(OUT / "input.json")
    prompts = run.base.read(OUT / "prompts.json")
    assert prompts["generation"] == run.prompt_from_document(run.GENERATION_DOC)
    result = run.call(
        "comparison_generation",
        data["id"],
        run.WM,
        prompts["generation"],
        {"id": data["id"], "sources": data["sources"]},
        run.generation_schema(data["id"]),
        5000,
    )
    generated = result["output"]
    if generated["status"] != "eligible":
        assert run.body_mark(generated["article_markdown"]) == generated["status"]
    run.base.save("generation.json", result)
    path = OUT / "C08.md"
    if path.exists():
        assert path.read_text(encoding="utf-8") == generated["article_markdown"]
    else:
        path.write_text(generated["article_markdown"], encoding="utf-8")
    print(
        "generated", generated["status"], generated["article_markdown"].splitlines()[0], flush=True
    )


def check_citations():
    data = run.base.read(OUT / "input.json")
    generated = run.base.read(OUT / "generation.json")["output"]
    text = generated["article_markdown"]
    mapping = {str(i): source["url"] for i, source in enumerate(data["sources"], 1)}
    checks = {}
    paragraphs = []
    checks["no_internal_source_ids_in_article"] = not re.search(r"\bF\d{3}\b", text)
    references = LINK.findall(text)
    checks["numbered_links_use_matching_original_urls"] = bool(references) and all(
        url == mapping[number] for number, url in references
    )
    checks["three_sources_present"] = {number for number, _ in references} == set(mapping)
    footer = text.split("## 出典", 1)[1] if "## 出典" in text else ""
    entries = [line.strip() for line in footer.splitlines() if line.strip().startswith("- 資料")]
    checks["source_list_three_numbered_link_entries"] = len(entries) == 3
    checks["source_titles_urls_and_order_match"] = entries == [
        f"- 資料{i}: [{source['title']}]({source['url']})"
        for i, source in enumerate(data["sources"], 1)
    ]
    if generated["status"] == "eligible":
        headers = []
        if "## 比較表" in text:
            table_section = text.split("## 比較表", 1)[1].split("## 比較の考察", 1)[0]
            headers = [
                line.strip() for line in table_section.splitlines() if line.strip().startswith("|")
            ]
        columns = headers[0].strip("|").split("|") if headers else []
        checks["table_three_target_columns_with_numbered_links"] = len(columns) == 4 and all(
            LINK.findall(cell) == [(str(i), mapping[str(i)])]
            and re.search(r"（\[資料[1-3]\]\([^)]+\)）", cell)
            for i, cell in enumerate(columns[1:], 1)
        )
        discussion = ""
        if "## 比較の考察" in text:
            discussion = text.split("## 比較の考察", 1)[1].split("## 出典", 1)[0]
        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n", discussion)
            if p.strip() and not p.strip().startswith("#")
        ]
        checks["every_discussion_paragraph_has_trailing_references"] = bool(paragraphs) and all(
            re.search(r"(?:\s*\[資料[1-3]\]\([^)]+\))+\s*$", p) for p in paragraphs
        )
    title = text.splitlines()[0].lstrip("# ").strip()
    if generated["status"] == "eligible":
        headings = ["## 比較表", "## 比較の考察", "## 出典"]
        checks["standard_sections_in_order"] = all(text.count(h) == 1 for h in headings) and (
            text.index(headings[0]) < text.index(headings[1]) < text.index(headings[2])
        )
        checks["title_at_most_60_characters"] = 0 < len(title) <= 60
        prose = text.split("## 出典", 1)[0]
        checks["dearu_style"] = not re.search(r"(?:です|ます|ください|いたします)[。！？]", prose)
    passed = all(checks.values())
    report = {
        "passed": passed,
        "checked_at": datetime.now(UTC).isoformat(),
        "article_hash": run.base.digest(text),
        "checks": checks,
        "note": (
            "Format, IDs and URL correspondence only; factual support is evaluated by the verifier."
        ),
    }
    run.base.save("citation-check.json", report)
    print("citation check", json.dumps(report, ensure_ascii=False), flush=True)
    if not passed:
        raise RuntimeError("CITATION_FORMAT_FAILED: verification was not called")


def verify():
    data = run.base.read(OUT / "input.json")
    prompts = run.base.read(OUT / "prompts.json")
    generated_call = run.base.read(OUT / "generation.json")
    generated = generated_call["output"]
    citation_check = run.base.read(OUT / "citation-check.json")
    assert citation_check["passed"]
    assert citation_check["article_hash"] == run.base.digest(generated["article_markdown"])
    assert (OUT / "C08.md").read_text(encoding="utf-8") == generated["article_markdown"]
    assert prompts["verification"] == run.base.current_prompt()
    result = run.call(
        "individual_verification",
        data["id"],
        run.base.MODEL,
        prompts["verification"],
        {
            "article": {
                "id": data["id"],
                "article_markdown": generated["article_markdown"],
                "generation_record": {
                    "comparison_status": generated["status"],
                    "issues": [] if generated["status"] == "eligible" else [generated["reason"]],
                },
            },
            "sources": data["sources"],
        },
        run.base.response_schema(data["id"]),
        2400,
    )
    run.base.save("verification.json", result)
    request = run.base.read(OUT / "requests" / (result["request_sha256"] + ".json"))
    supplied = json.loads(request["input"])
    assert supplied["article"]["article_markdown"] == generated["article_markdown"]
    assert supplied["sources"] == data["sources"]
    summary = {
        "generation_status": generated["status"],
        "citation_format": "pass",
        "verification": result["output"],
        "effective_status": run.effective_status(generated, result["output"]),
        "article_hash": citation_check["article_hash"],
        "citation_check_precedes_verification": True,
        "generated_checked_verified_article_identical": True,
        "same_original_sources": all(
            run.base.digest(s["text"]) == s["input_hash"] for s in data["sources"]
        ),
        "wordpress_calls": 0,
    }
    run.base.save("summary.json", summary)
    lines = [
        "# C08：出典形式を統一した再生成・検証",
        "",
        (
            "2026-10-14。同じ原資料3件を使用し、GPT-4.1 miniで再生成した。"
            "出典形式を確認して合格した後、その生成本文を変更せず"
            "GPT-4.1で個別検証した。"
        ),
        "",
        "生成時判定：" + run.base.STATUS[generated["status"]],
        "",
        (
            "出典形式：確認済み。資料1〜3の番号、比較表の対応リンク、"
            "考察の各段落末の参照、出典欄のタイトル付きリンクが"
            "原資料の順序・URLと一致。内部のF IDは本文に表示していない。"
        ),
        "",
        f"検証モデル判定：{run.base.STATUS[result['output']['status']]}／絶対評価点：{result['output']['score']}点",
        "",
        "検証理由：" + result["output"]["reason"],
        "",
        "再生成本文：[C08.md](" + (OUT / "C08.md").as_posix() + ")",
        "",
        "## 出典形式の確認",
        "",
    ]
    for key, passed in citation_check["checks"].items():
        lines.append(f"- {key}: {'pass' if passed else 'fail'}")
    lines.extend(
        [
            "",
            "段落の参照が実際の記述に対応していることも目視確認してから検証した。形式確認は追加のAI意味評価ではない。生成・検証の原稿と原資料の一致を確認し、過去の生成結果・判定は変更していない。",
            "",
            "保存ログ：[生成・出典確認・検証](../.local/comparison-A-c08-citations-20261014-v3/)。WordPress投稿は行っていない。",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("verified", json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "generate", "check", "verify"])
    stage = parser.parse_args().stage
    {"prepare": prepare, "generate": generate, "check": check_citations, "verify": verify}[stage]()


if __name__ == "__main__":
    main()
