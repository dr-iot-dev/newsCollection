# ruff: noqa: E501, RUF001
"""Offline report and evidence checks for the frozen marked v3.2 experiment."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/comparison-generation-marked-reevaluation-20261014-v3-2"
PRIOR = ROOT / ".local/comparison-generate-then-evaluate-experiment-20261014-v2"


def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save(name, v):
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    summary = read(OUT / "summary.json")
    docs = read(OUT / "documents.json")
    lookup = {d["id"]: d for d in docs}
    ids = set(lookup)
    expected_pairs = {a + "|" + b for a, b in itertools.combinations(sorted(ids), 2)}
    runs = {
        method: [read(OUT / "benchmarks" / f"{method}-{i}.json") for i in range(1, 4)]
        for method in ["A", "B"]
    }
    calls = [read(p) for p in (OUT / "calls").glob("*.json")]
    assert len(calls) == 34
    relations = Counter()
    adjustments = 0
    transmitted_articles = 0
    for method, values in runs.items():
        for v in values:
            result = v["result"]
            assert {a["id"] for a in result["articles"]} == ids
            assert (
                set(result["pair_checks"]) == expected_pairs
                and not result["pair_validation_errors"]
            )
            assert not result["shared_exact_hash_groups"]
            relations.update(p["relation"] for p in result["pair_checks"].values())
            if method == "B":
                assert not v["adjustment_errors"]
                adjustments += sum(x["changed"] for x in v["quality_adjustments"].values())
            for a in result["articles"]:
                assert not a["technical_errors"]
                allpass = all(
                    a["assessment"][k]["status"] == "pass"
                    for k in ["distinct_targets", "common_decision", "source_fidelity"]
                )
                assert allpass == (a["assessment"]["quality"] is not None)
                assert (a["comparison_status"] == "eligible") == (a["normal_score"] is not None)
    for r in calls:
        request = read(OUT / "requests" / (r["request_sha256"] + ".json"))["payload"]
        assert request["model"] == "gpt-4.1-2025-04-14" and request["temperature"] == 0
        data = json.loads(request["input"])
        if r["tag"].startswith("facts:"):
            continue
        articles = data.get("articles", [data.get("article")])
        for item in articles:
            d = lookup[item["id"]]
            assert (
                item["article_markdown"] == d["article_markdown"]
                and item["source_article_ids"] == d["source_article_ids"]
            )
            assert item["generation_history"] == {
                k: d["generation_record"][k]
                for k in ["comparison_status", "issues", "generation_checks"]
            }
            for source in item["original_sources"]:
                assert hashlib.sha256(source["text"].encode()).hexdigest() == source["input_hash"]
            assert "common_verification" not in item and "previous_score" not in item
            transmitted_articles += 1
    with (OUT / "article-assessments.csv").open(encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.DictReader(f))) == 42
    assert len(read(OUT / "blocked-by-original-marks.json")) == 7
    assert all(x["normal_score"] is None for x in read(OUT / "blocked-by-original-marks.json"))
    assert all(
        x["unchanged"]
        for x in read(OUT / "saved-article-integrity.json")["original_20_files_unchanged"]
    )
    save(
        "completion-validation.json",
        {
            "passed": True,
            "complete_runs": 6,
            "article_assessments": 42,
            "pair_assessments": sum(relations.values()),
            "pair_relations": dict(relations),
            "generation_history_article_occurrences_verified": transmitted_articles,
            "technical_errors": 0,
            "quality_adjustments": adjustments,
            "common_exclusions_preserved": 7,
            "original_20_files_unchanged": True,
        },
    )
    for d in docs:
        p = OUT / "articles" / (d["id"] + ".md")
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(d["article_markdown"].encode("utf-8"))
        assert (
            hashlib.sha256(p.read_bytes()).hexdigest()
            == hashlib.sha256(d["article_markdown"].encode()).hexdigest()
        )
    d = lookup["H008-1"]
    source = next(s for s in d["sources"] if s["f_id"] == "F110")
    unsupported = "現時点ではAI活用は限定的、今後の機能拡充での活用予定"
    assert (
        unsupported in d["article_markdown"]
        and "AI" not in source["text"]
        and "人工知能" not in source["text"]
    )
    findings = {
        "reviewer": "Codex assistant read-only source and article review; not independent human gold",
        "model_results_preserved": True,
        "findings": [
            {
                "id": "H008-1",
                "review_status": "ineligible",
                "normal_score": None,
                "category": "unsupported_planned_capability",
                "article_claim": unsupported,
                "source_id": "F110",
                "source_url": source["url"],
                "source_sha256": source["input_hash"],
                "reason": "F110 describes data integration, report creation and proposed construction/personnel databases. It provides no statement of current AI use or planned AI expansion. Nonmention does not establish limited support or a planned AI capability.",
                "shared_fact_model_status": "pass",
                "A_model_statuses": ["eligible"] * 3,
                "B_model_statuses": ["eligible"] * 3,
                "method_specific_fault": False,
            },
            {
                "id": "H020-0",
                "review_status": "needs_confirmation",
                "normal_score": None,
                "category": "common_decision_not_established",
                "reason": "The returned question lists sustainability, introduction and collaboration generally, with business/municipal/household readers. It does not establish one concrete decision involving community-farm operation, commercial wasabi cultivation and a household application. These different roles can be compared if the article explains their contribution to one decision; domain differences alone do not warrant rejection.",
                "independent_human_gold": False,
            },
        ],
    }
    save("review-findings.json", findings)
    ledger = {}
    for folder in [
        ROOT / ".local/comparison-generation-marked-reevaluation-20261014-v3",
        ROOT / ".local/comparison-generation-marked-reevaluation-20261014-v3-1",
        OUT,
    ]:
        for p in (folder / "calls").glob("*.json"):
            r = read(p)
            h = r["request_sha256"]
            if h in ledger:
                assert ledger[h]["estimated_usd"] == r["estimated_usd"]
            else:
                ledger[h] = {"tag": r["tag"], "estimated_usd": r["estimated_usd"], "seen_in": []}
            ledger[h]["seen_in"].append(folder.name)
    new_calls = [c for c in calls if c.get("new_api_call", True)]
    cost = {
        "logical_final_calls": 34,
        "reused_calls": 34 - len(new_calls),
        "new_successful_calls": len(new_calls),
        "final_dataset_estimated_usd": summary["estimated_usd"],
        "new_successful_calls_estimated_usd": sum(c["estimated_usd"] for c in new_calls),
        "unique_successful_calls_including_pilots": len(ledger),
        "including_pilots_estimated_usd": sum(r["estimated_usd"] for r in ledger.values()),
        "pilot_only_estimated_usd": sum(
            r["estimated_usd"]
            for h, r in ledger.items()
            if not (OUT / "calls" / (h + ".json")).exists()
        ),
        "ledger": ledger,
        "basis": "saved usage and fixed rates in experiment script; estimate, not invoice",
    }
    save("cost-ledger.json", cost)
    artifact_audit = read(PRIOR / "artifact-audit.json")
    save("article-artifact-audit.json", {label: artifact_audit[label] for label in ids})
    decision = {
        "status": "not_ready_for_production_selection",
        "selected_method": None,
        "preference_from_stability_alone": False,
        "reason": "Both methods accept all seven in all three trials. Shared factual verification missed an unsupported planned AI claim; broad common-decision answers remain. Neither method establishes safe publication on this sample.",
        "A_estimated_usd": summary["metrics"]["A"]["estimated_usd"],
        "B_estimated_usd": summary["metrics"]["B"]["estimated_usd"],
        "source_review_rejections": ["H008-1"],
        "source_review_holds": ["H020-0"],
        "complete_duplicate_positive_cases_in_native_sample": 0,
        "shared_exact_hash_guard_tested": True,
        "independent_human_gold": False,
        "original_model_decisions_preserved": True,
    }
    save("decision.json", decision)
    progress = read(OUT / "progress.json")
    progress.update(
        checked_at=datetime.now(UTC).isoformat(),
        status="reevaluation_complete",
        A_completed_trials=3,
        B_completed_trials=3,
        method_decision=decision["status"],
        new_successful_api_calls_in_v3_2=len(new_calls),
        blocking_api_error=None,
    )
    progress["latest_api_error_is_historical"] = True
    save("progress.json", progress)
    metrics = summary["metrics"]
    acost = metrics["A"]["estimated_usd"]
    bcost = metrics["B"]["estimated_usd"]
    lines = [
        "# 生成時マークを保持した再評価結果",
        "",
        "実施日：2026-10-14。APIクレジット反映後、固定条件v3.2のA/B各3回を完了した。保存済みデータを再利用し、追加本文生成は行っていない。",
        "",
        "**結論：採否の反転はなくなったが、原資料にないAI活用予定を含む記事が両方式で採用された。構造の修正だけで採用判断が正しくなったとはいえず、この結果で本番方式を確定しない。** 問題は採否の揺れではなく、共通検証の見逃しと、具体的な判断の成立を広いテーマの一致で認めている点にある。",
        "",
        "## 指示・出力設計の修正",
        "",
        "- 読者、具体的な判断の問い、3対象の名称・役割を先に出力させた。別対象・共通判断目的・原資料への忠実さの3条件を、個別のpass/fail/uncertainと理由・引用で記録する。",
        "- 3条件が全てpassの場合だけ品質点を出す。不適・未確認はqualityと通常点をnullにし、高得点から採用へ救済しない。3者目の貢献は説明・品質評価に用い、計画にない第4の必須条件にはしない。",
        "- 生成時マーク・理由・確認記録を来歴として保持し、eligibleを正解扱いしない。以前の適否検証の肯定結論・点数・順位は入力から除いた。原資料そのものを読み、事実検証をA/B共通工程として固定した。",
        "- 特定の評価事例の名称を指示から除いた。異なる役割でも具体的な選択・工程設計に役立てば認める一方、広い効率化だけで共通判断ありとしないよう指示した。",
        "- 全21ペアの重複判定を必須にし、引用IDを対応する記事の本文箇所に限定した。本文ハッシュ一致の完全複製は両方式共通のコードで除外する。",
        "- Aは一括の適否→条件付き品質→全ペア確認。Bは個別の同じ適否→品質→全文による全体確認。Bの全体確認から個別不適を採用に戻さない。モデル・設定・ルーブリック・入力を固定し、同順2回と順序変更1回で比較した。",
        "",
        "## 再利用と共通除外",
        "",
        "|工程|件数|扱い|",
        "|---|---:|---|",
        "|保存済み実生成|14|原文・本文・生成時マークを保持|",
        "|生成時ineligible|6|共通処理で除外、通常点null|",
        "|元の別モデル検証による追加除外|1|共通除外を維持、通常点null|",
        "|A/B比較対象|7|同じ本文・原資料を使用|",
        "|完了済み原資料照合|7|再利用。モデル結果は全件pass|",
        "|Bの1回目の個別判定|2|指示・入力・スキーマ・モデル・出力上限の一致を確認して再利用|",
        "",
        "旧20本とマークを持たない人工複製は、今回の方式比較から除外した。旧20本のハッシュ一致、実生成14組の生成応答・本文・原資料ハッシュを確認した。現行条件と異なるv3/v3-1の一括結果は先行試行として保存し、比較集計に混ぜない。共通除外7件が採点対象に戻ったこともない。",
        "",
        "## A/Bの実測",
        "",
        "|指標|A：一括|B：個別＋全体|",
        "|---|---:|---:|",
        "|採用数（同順1／同順2／順序変更）|7／7／7|7／7／7|",
        "|採否が反転した記事|0|0|",
        f"|記事別の最大点数幅|{max(x['score_range_if_scored'] for x in metrics['A']['articles'])}点|{max(x['score_range_if_scored'] for x in metrics['B']['articles'])}点|",
        "|採点工程の要求数（3回分）|3|24|",
        f"|採点工程の推定費用|USD {acost:.6f}|USD {bcost:.6f}|",
        "|全体確認による点数調整|一括内で採点|0件|",
        "",
        "|記事・テーマ|Aの点（1／2／3）|Bの点（1／2／3）|",
        "|---|---|---|",
    ]
    labels = {
        "H008-1": "C08：業界別AI・データ活用",
        "H012-0": "C12：健康管理支援",
        "H015-0": "C15：企業IT",
        "H020-0": "C20：農業・栽培",
        "H023-0": "C23：スマートホーム",
        "H029-0": "C29：企画AI・ナレッジ",
        "H030-0": "C30：医療AI",
    }
    for label in sorted(ids):
        a = next(x for x in metrics["A"]["articles"] if x["id"] == label)
        b = next(x for x in metrics["B"]["articles"] if x["id"] == label)
        link = f"[{labels[label]}](../.local/{OUT.name}/articles/{label}.md)"
        lines.append(
            "|"
            + link
            + "|"
            + "／".join(map(str, a["scores"]))
            + "|"
            + "／".join(map(str, b["scores"]))
            + "|"
        )
    lines += [
        "",
        "両方式で採用集合は同じだった。Aの方が安いが、Bにはこの標本で不適混入を減らした実測上の優位がない。Bの点数幅は小さいものの、その一点でBを選ぶ理由にはしない。3回目の点数差は、順序の影響と再実行の揺れを分離できないため、提示順による因果とは断定しない。",
        "",
        "## 原資料と理由の点検で残った問題",
        "",
        "### C08：共通原資料照合が、記載のないAI活用予定を通していた",
        "",
        "記事のe-Stand欄に「"
        + unsupported
        + "」とある。保存原資料F110の全文は、データ連携、工事報告書の提供、施工実績DB・タレントマネジメントの機能案を説明しているが、AIの利用状況やAI活用予定を述べていない。未記載から「限定的」「今後予定」を確定できない。この記述を含む本文は、そのまま採用しない。",
        "",
        "新しい共通事実検証はこの欄をsupportedとし、A/Bとも共通source_fidelity=passを入力した結果、C08を3回とも採用した。これはA/Bに共通する検証の見逃しであり、B固有の欠陥や一括方式固有の欠陥として数えない。根拠不足の認定は今回のCodexによる保存原文の点検であり、独立した人による正解ラベルではない。モデルの元結果は変更せず、追加点検記録でC08をineligible・通常点nullとした。",
        "",
        "### 共通判断の理由が、具体的な選択・工程に十分結び付いていない",
        "",
        "C08のAは「自社の業務効率化やDX推進のために比較・選択」、Bは「自組織の用途・業界に応じて比較・選択」を理由にpassとしている。どちらも小売店舗運営・建設現場管理・研究事業化の3者を、一つの具体的な判断でどう使うかを示していない。「読者」「問い」の欄を必須にしても、広い括りを言い直す出力を防げなかった。",
        "",
        "C20も、共同農園、商業的なわさび生産設備、家庭向けアプリを「持続可能な食と農」「導入・協業」でまとめる回答になった。分野や役割の違い自体で却下するのではなく、この本文に共通の具体的判断が成立するかを未確認として残す。追加点検記録はneeds_confirmation・通常点null。こうした読解判断を独立した人の正解として精度計算には使わない。",
        "",
        "出力の欠落・引用IDの不整合を防ぐ修正は機能したが、意味的な適否判定の改善まで達成したとはいえない。適否条件は今後も緩めず、共通事実検証と具体的な判断を確認する工程の修正が必要である。",
        "",
        "## 完全複製と公開用成果物",
        "",
        "実生成7記事には完成記事の完全複製がない。全6試行の126ペアは全てdistinctとなり、過剰統合は起きなかったが、陽性例がないので意味的重複の検出率や見逃し0を証明できない。人工のマークなし事例を追加API評価に使ってはいない。本文ハッシュ一致の複製除外はローカルのコード検査で確認し、モデルの検出能力の実測とは区別した。",
        "",
        "保存本文は変更していない。前回の成果物検査ではC15/C20/C29/C30にMarkdown表の崩れ、C20/C23/C29/C30に原リリースURLの欠落がある。5記事の形式問題は採点結果と別に記録してあり、モデルがeligibleとしても、そのまま公開できる成果物とは扱わない。",
        "",
        "## 費用と検証",
        "",
        f"固定条件の保存成功応答34件分は推定USD {summary['estimated_usd']:.6f}（A {acost:.6f}、B {bcost:.6f}、共通事実検証 {summary['common_facts_usd']:.6f}）。うち9件を再利用したため、今回再開後に新たに成功したAPI要求は25件、推定USD {cost['new_successful_calls_estimated_usd']:.6f}。",
        f"先行試行も含む重複除去後の保存成功応答は{cost['unique_successful_calls_including_pilots']}件、推定USD {cost['including_pilots_estimated_usd']:.6f}。今回の34件に含まれない先行試行分はUSD {cost['pilot_only_estimated_usd']:.6f}。保存usageと実験スクリプトの固定単価による概算であり、請求実績とは異なる。",
        "",
        "6試行・42記事判定・126ペア判定を検査した。各記事の生成時マーク・本文・原資料ハッシュ、全ペアの存在、通常点の条件、引用IDの所属、Bの調整契約に技術検査エラーは0件。品質点による不適の救済禁止、ハッシュ複製除外、請求エラー後の再開もローカル検査済み。引用が実在することは、引用による主張の裏付けを保証しない。",
        "",
        "## 判断と証跡",
        "",
        "A/Bの本番方式は未確定とする。今回確認できたのは構造・反復結果・費用であり、根拠のない採用を避けるという目的はまだ満たしていない。採否が安定したために両方式を承認することも、マークなし人工複製の旧結果を持ち出してBを不採用にすることもしない。独立した人の評価、未使用記事での確認、意味的重複の陽性評価は未実施。",
        "",
        f"- [集計](../.local/{OUT.name}/summary.json)・[42件の判定一覧](../.local/{OUT.name}/article-assessments.csv)",
        f"- [原資料点検の追加記録](../.local/{OUT.name}/review-findings.json)・[成果物形式検査](../.local/{OUT.name}/article-artifact-audit.json)",
        f"- [実行完了検査](../.local/{OUT.name}/completion-validation.json)・[費用と再利用の台帳](../.local/{OUT.name}/cost-ledger.json)",
        f"- [固定条件](../.local/{OUT.name}/policy.json)・[指示全文](../.local/{OUT.name}/prompts.json)・[入力ハッシュ](../.local/{OUT.name}/input-manifest.json)",
        f"- [判断記録](../.local/{OUT.name}/decision.json)・[進捗](../.local/{OUT.name}/progress.json)",
        "- [修正前のマーク付き評価](comparison-generation-marked-evaluation-20261014.md)",
    ]
    (ROOT / "docs/comparison-generation-marked-reevaluation-20261014.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "complete_runs": 6,
                "technical_errors": 0,
                "model_adopted_counts": {"A": [7, 7, 7], "B": [7, 7, 7]},
                "new_api_calls": len(new_calls),
                "new_api_estimated_usd": cost["new_successful_calls_estimated_usd"],
                "method_decision": decision["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
