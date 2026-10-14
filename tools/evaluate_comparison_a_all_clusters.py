# ruff: noqa: E402, RUF001
"""Apply the same individual evaluation to every saved cluster comparison."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import evaluate_comparison_a_individual as base

OUT = ROOT / ".local/comparison-A-individual-all30-20261014"
FIRST5 = base.OUT
base.OUT = OUT
REPORT = ROOT / "docs/comparison-A-individual-all30-results-20261014.md"


def prepare():
    prompt = base.current_prompt()
    assert prompt == base.read(FIRST5 / "instructions.json")["instructions"]
    mapping = {r["id"]: r for r in base.read(base.SAVED / "private-mapping.json")}
    documents = []
    coverage = []
    for source in base.read(base.SAVED / "legacy-documents.json"):
        meta = mapping[source["id"]]
        path = ROOT / "docs" / meta["article"]
        markdown = path.read_text(encoding="utf-8")
        assert markdown == source["article_markdown"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"]
        doc = {
            "id": source["id"],
            "cluster": meta["cluster"],
            "article_path": path.as_posix(),
            "article_hash": base.digest(markdown),
            "article_markdown": markdown,
            "sources": source["sources"],
            "generation_record": source["generation_record"],
            "origin": "original twenty completed edited comparisons",
        }
        documents.append(doc)
        coverage.append({"cluster": meta["cluster"], "evaluated_article_id": doc["id"]})
    for attempts in base.read(base.SAVED / "new-generation-summary.json"):
        complete = []
        history = []
        for attempt in attempts:
            request_hash = attempt["generation_request_sha256"]
            call = base.read(base.SAVED / "calls" / (request_hash + ".json"))
            original = call["output"]
            markdown = original["article_markdown"]
            generated_body = markdown.lstrip().startswith("#")
            history.append(
                {
                    "attempt": attempt["attempt"],
                    "generation_status": original["comparison_status"],
                    "issues": original["issues"],
                    "generated_body": generated_body,
                    "generation_request_sha256": request_hash,
                    "article_hash": base.digest(markdown),
                }
            )
            if not generated_body:
                continue
            source = attempt["document"]
            assert source["article_markdown"] == markdown
            assert source["generation_record"] == original
            article_id = source["id"]
            article_path = OUT / "articles" / (article_id + ".md")
            article_path.parent.mkdir(parents=True, exist_ok=True)
            if article_path.exists():
                assert article_path.read_text(encoding="utf-8") == markdown
            else:
                article_path.write_text(markdown, encoding="utf-8")
            complete.append(
                {
                    "id": article_id,
                    "cluster": attempt["cluster"],
                    "article_path": article_path.as_posix(),
                    "article_hash": base.digest(markdown),
                    "article_markdown": markdown,
                    "sources": source["sources"],
                    "generation_record": {
                        "comparison_status": original["comparison_status"],
                        "issues": original["issues"],
                    },
                    "original_generation_record": original,
                    "generation_request_sha256": request_hash,
                    "origin": "saved native generated comparison without later editorial revisions",
                }
            )
        assert len(complete) <= 1
        documents.extend(complete)
        coverage.append(
            {
                "cluster": attempts[0]["cluster"],
                "evaluated_article_id": complete[0]["id"] if complete else None,
                "generation_attempts": history,
                "no_article_reason": "生成時に不適とされ、比較本文は作られていない"
                if not complete
                else None,
            }
        )
    assert len(documents) == 28 and len(coverage) == 30
    assert {c["cluster"] for c in coverage} == {f"C{i:02d}" for i in range(1, 31)}
    for doc in documents:
        assert len(doc["sources"]) == 3
        for source in doc["sources"]:
            assert base.digest(source["text"]) == source["input_hash"]
    base.save("instructions.json", base.read(FIRST5 / "instructions.json"))
    base.save("documents.json", documents)
    base.save("coverage.json", sorted(coverage, key=lambda c: c["cluster"]))
    base.save(
        "policy.json",
        {
            "model": base.MODEL,
            "prompt_version": base.VERSION,
            "articles": 28,
            "clusters": 30,
            "reuse_first5_only_on_exact_request_match": True,
            "articles_per_call": 1,
            "sources_per_call": 3,
            "sources_full_text": True,
            "previous_scores_or_verification_results_supplied": False,
            "generation_status_and_issues_retained": True,
            "missing_generation_record_is_not_rejection": True,
            "pair_checks": False,
            "twelve_check_gate": False,
            "article_rewrite": False,
            "semantic_post_filter": False,
            "score": "absolute 0-100 regardless of suitability; no adoption score threshold",
            "wordpress_write": False,
        },
    )
    print("prepared 28 articles covering 30 clusters; two clusters have no article", flush=True)


def payload_for(doc, prompt):
    return {
        "model": base.MODEL,
        "instructions": prompt,
        "input": base.canonical(
            {
                "article": {
                    "id": doc["id"],
                    "article_markdown": doc["article_markdown"],
                    "generation_record": doc["generation_record"],
                },
                "sources": doc["sources"],
            }
        ),
        "store": False,
        "temperature": 0,
        "max_output_tokens": 2400,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "individual_comparison_evaluation",
                "strict": True,
                "schema": base.response_schema(doc["id"]),
            }
        },
    }


def one(doc, prompt):
    payload = payload_for(doc, prompt)
    uid = base.digest(base.canonical(payload))
    base.save("requests/" + uid + ".json", payload)
    response_path = OUT / "responses" / (uid + ".json")
    reused = (FIRST5 / "responses" / (uid + ".json")).exists()
    if not response_path.exists() and reused:
        assert base.read(FIRST5 / "requests" / (uid + ".json")) == payload
        response_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIRST5 / "responses" / (uid + ".json"), response_path)
    if not response_path.exists():
        for saved_transport in sorted((OUT / "transport").glob(uid + "-*.json")):
            acknowledged = base.read(saved_transport)
            if (
                acknowledged.get("status") == "completed"
                and acknowledged.get("model") == base.MODEL
            ):
                base.save("responses/" + uid + ".json", acknowledged)
                break
    if response_path.exists():
        raw = base.read(response_path)
    else:
        intent = "intents/" + uid + ".json"
        if (OUT / intent).exists():
            raise RuntimeError("REQUEST_OUTCOME_UNKNOWN: no blind repeat for " + doc["id"])
        base.save(intent, {"id": doc["id"], "sent_at": datetime.now(UTC).isoformat()})
        print("evaluating", doc["cluster"], doc["id"], flush=True)
        with httpx.Client(
            trust_env=False, follow_redirects=False, timeout=httpx.Timeout(240, connect=15)
        ) as client:
            for attempt in range(3):
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    json=payload,
                    headers={"Authorization": "Bearer " + base.api_key()},
                )
                raw = response.json()
                base.save(f"transport/{uid}-{attempt}.json", raw)
                code = (raw.get("error") or {}).get("code")
                if response.status_code == 429 and code == "rate_limit_exceeded" and attempt < 2:
                    time.sleep(15)
                    continue
                base.save("responses/" + uid + ".json", raw)
                if response.status_code != 200:
                    raise RuntimeError(f"API_HTTP_{response.status_code}:{code}")
                break
    if raw.get("status") != "completed":
        raise RuntimeError("INCOMPLETE_RESPONSE: " + doc["id"])
    assert raw["model"] == base.MODEL
    text = "".join(
        c.get("text", "")
        for o in raw["output"]
        if o["type"] == "message"
        for c in o["content"]
        if c["type"] == "output_text"
    )
    value = json.loads(text)
    base.validate_output(value, doc["id"])
    result = {
        "cluster": doc["cluster"],
        "article_path": doc["article_path"],
        "article_hash": doc["article_hash"],
        "origin": doc["origin"],
        "request_sha256": uid,
        "response_id": raw["id"],
        "model": raw["model"],
        "usage": raw["usage"],
        "reused_from_first5": reused,
        "output": value,
    }
    base.save("results/" + doc["id"] + ".json", result)
    print(doc["cluster"], base.STATUS[value["status"]], value["score"], flush=True)
    return result


def finish(documents, results, coverage, prompt):
    for doc, result in zip(documents, results, strict=True):
        request = base.read(OUT / "requests" / (result["request_sha256"] + ".json"))
        assert request == payload_for(doc, prompt)
        assert (
            base.digest(Path(doc["article_path"]).read_text(encoding="utf-8"))
            == doc["article_hash"]
        )
        assert all(base.digest(s["text"]) == s["input_hash"] for s in doc["sources"])
    counts = Counter(r["output"]["status"] for r in results)
    reused = sum(r["reused_from_first5"] for r in results)
    summary = {
        "clusters": 30,
        "evaluated_articles": len(results),
        "new_successful_evaluations": len(results) - reused,
        "reused_first5_evaluations": reused,
        "status_counts": {base.STATUS[k]: counts[k] for k in base.STATUS},
        "no_article_clusters": [
            c["cluster"] for c in coverage if c["evaluated_article_id"] is None
        ],
        "model": base.MODEL,
        "score_min": min(r["output"]["score"] for r in results),
        "score_max": max(r["output"]["score"] for r in results),
        "usage_total": {
            key: sum(r["usage"][key] for r in results)
            for key in ["input_tokens", "output_tokens", "total_tokens"]
        },
    }
    assert len(results) == 28 and reused == 5
    base.save("results.json", results)
    base.save("summary.json", summary)
    base.save(
        "validation.json",
        {
            "all_30_clusters_accounted_for": True,
            "all_28_completed_articles_evaluated": True,
            "first5_exact_request_match_and_no_second_call": True,
            "same_prompt_model_settings_for_all_articles": True,
            "one_article_and_its_three_full_sources_per_request": True,
            "all_source_and_article_hashes_unchanged": True,
            "output_schema_valid": True,
            "prior_quality_scores_or_verifier_verdicts_supplied": False,
            "semantic_post_filter": False,
            "wordpress_calls": 0,
        },
    )
    by_id = {r["output"]["id"]: r for r in results}
    by_doc = {d["id"]: d for d in documents}
    lines = [
        "# 全30クラスターの比較記事：個別評価のまとめ",
        "",
        "実施日：2026-10-14。現在の修正指示と絶対評価スコアを使用。記事1本とその原資料3件の全文だけを1要求に渡した。GPT-4.1-2025-04-14、temperature=0。以前の点数・検証結果・facts抜粋・他記事は入力していない。",
        "",
        f"30クラスター中、完成した比較本文28本を評価した。適切{counts['eligible']}本、不適{counts['ineligible']}本、要確認{counts['needs_confirmation']}本。先行5件を要求完全一致で再利用し、追加評価は23件。C11・C28は生成時に不適となり本文が作られていないため、評価点は付けていない。",
        "",
        "## 全クラスター一覧",
        "",
        "|クラスター|記事・生成状況|今回のモデル判定|絶対評価点／100|",
        "|---|---|---|---:|",
    ]
    for cluster in coverage:
        article_id = cluster["evaluated_article_id"]
        if article_id is None:
            lines.append(f"|{cluster['cluster']}|生成時不適・比較本文なし|評価対象本文なし|—|")
            continue
        doc, result = by_doc[article_id], by_id[article_id]
        title = doc["article_markdown"].splitlines()[0].lstrip("# ")
        lines.append(
            f"|{cluster['cluster']}|[{title}]({doc['article_path']})|"
            f"{base.STATUS[result['output']['status']]}|{result['output']['score']}|"
        )
    lines.extend(["", "## 各記事のモデル判定理由", ""])
    for cluster in coverage:
        article_id = cluster["evaluated_article_id"]
        lines.extend(["### " + cluster["cluster"], ""])
        if article_id is None:
            lines.append(
                "比較本文がないため今回のAI評価は実行していない。以下は保存した生成時の不適理由であり、今回のモデルによる判定ではない。"
            )
            for attempt in cluster["generation_attempts"]:
                reasons = "／".join(i.get("explanation", "") for i in attempt["issues"])
                lines.extend(["", f"試行{attempt['attempt']}：{reasons}"])
        else:
            result = by_id[article_id]
            lines.append(result["output"]["reason"])
            label = "初期5件を再利用" if result["reused_from_first5"] else "今回の追加評価"
            origin = (
                "以前に編集した完成記事"
                if by_doc[article_id]["origin"].startswith("original")
                else "保存した生成本文そのもの（後のv7編集は不使用）"
            )
            lines.extend(["", f"評価対象：{origin}。{label}。"])
        lines.append("")
    lines.extend(
        [
            "## 実送信指示",
            "",
            "```text",
            prompt,
            "```",
            "",
            "## 集計と確認範囲",
            "",
            "スコアはモデルが各記事を個別に絶対評価した値であり、集計時にも順位や他記事を理由に調整していない。不適・要確認にもスコアを記録し、点数で採否を変更していない。モデル結果の後に手動の意味評価や12項目の合否集計を追加していない。",
            "",
            "20本は以前に編集した完成版、8本は追加10クラスターの保存済み生成本文で、編集段階が異なる。この違いを採点方式の性能差として扱わない。C07は過去の共通検証で除外されたが、生成時は適切とされた本文が存在するため、今回の指示で評価対象に含めた。過去の共通検証結果は入力していない。C11・C28の生成時不適を今回のモデルの不適検出件数に混ぜていない。",
            "",
            "同じ指示・モデル・設定、各要求の記事と原資料、出力形式、元本文・原資料のハッシュ不変、先行5件の要求完全一致を確認した。採点の再現性や、全記事の事実精度を独立した正解で測る評価は行っていない。WordPress投稿は行っていない。",
            "",
            "保存先：[要求・応答・個別結果・全体集計](../.local/comparison-A-individual-all30-20261014/)。summary.jsonは集計、validation.jsonは入力・出力・ハッシュの確認記録。",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)


def record_known_issue_observations():
    results = {r["cluster"]: r for r in base.read(OUT / "results.json")}
    observations = {
        "basis": (
            "Previously documented content problems compared with saved model results; "
            "no additional AI review or verdict override"
        ),
        "prior_report": "docs/comparison-generation-marked-reevaluation-20261014.md",
        "findings": [
            {
                "cluster": "C07",
                "article_id": "H007-1",
                "known_issue": (
                    "F809とF876は同じジャスミー・パナソニック共同発表を"
                    "別対象として2列に掲載している"
                ),
                "article_excerpt": "同左（F809と同内容）",
                "model_output": results["C07"]["output"],
            },
            {
                "cluster": "C08",
                "article_id": "H008-1",
                "known_issue": (
                    "e-Standの原資料F110はAIの利用状況・活用予定を述べていないが"
                    "本文は限定的利用と将来予定を断定している"
                ),
                "article_excerpt": "現時点ではAI活用は限定的、今後の機能拡充での活用予定",
                "model_output": results["C08"]["output"],
            },
        ],
        "model_statuses_modified": False,
        "new_semantic_post_filter_added": False,
    }
    base.save("known-issue-observations.json", observations)
    heading = "## 既知の問題と今回の判定の食い違い"
    report = REPORT.read_text(encoding="utf-8")
    if heading in report:
        return
    note = "\n".join(
        [
            "",
            heading,
            "",
            "モデルは28本すべてを適切としたが、過去に原資料・生成本文で確認した次の問題も通過した。今回の指示には、同じ対象の重複や原資料にない重要な事実を不適とする文言があるため、この結果を不適除外の目的が達成された証拠とは扱えない。",
            "",
            "|クラスター|以前に確認した問題|今回のモデル判定|点数|",
            "|---|---|---|---:|",
            f"|C07|同じジャスミー・パナソニック共同発表F809/F876を別対象として掲載。本文にも「同左（F809と同内容）」とある|{base.STATUS[results['C07']['output']['status']]}|{results['C07']['output']['score']}|",
            f"|C08|F110に裏付けのないe-StandのAI活用状況・将来予定を本文が断定|{base.STATUS[results['C08']['output']['status']]}|{results['C08']['output']['score']}|",
            "",
            "C07のモデル理由は協業のWeb3プラットフォーム2件を認識しながら適切とした。C08のモデル理由は、裏付けのないAI活用状況・予定を「正しく記載」と明示している。点数も92点・95点であり、高いスコアを採用の根拠に代用することはできない。",
            "",
            "これは今回の出力と過去の確認済み記録との対照であり、追加AI審査や全記事の再点検を行ったものではない。元のモデル判定・点数は変更していない。食い違いはknown-issue-observations.jsonへ別記録とした。現行指示・モデルでは少なくともこれらの問題が除外されていない。",
            "",
        ]
    )
    marker = "## 全クラスター一覧"
    assert marker in report
    REPORT.write_text(report.replace(marker, note + "\n" + marker, 1), encoding="utf-8")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ["prepare", "evaluate"]:
        raise SystemExit("usage: evaluate_comparison_a_all_clusters.py prepare|evaluate")
    if sys.argv[1] == "prepare":
        prepare()
        return
    documents = base.read(OUT / "documents.json")
    coverage = base.read(OUT / "coverage.json")
    prompt = base.read(OUT / "instructions.json")["instructions"]
    assert prompt == base.current_prompt()
    results = [one(doc, prompt) for doc in documents]
    finish(documents, results, coverage, prompt)
    record_known_issue_observations()


if __name__ == "__main__":
    main()
