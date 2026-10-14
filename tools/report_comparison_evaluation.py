# ruff: noqa: E501, RUF001
"""Offline reproducible metrics and report, no API calls."""

import csv
import json
import math
import re
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/comparison-generate-then-evaluate-experiment-20261014-v2"
OLD = ROOT / ".local/comparison-generate-then-evaluate-experiment-20261014"


def rd(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save(n, v):
    (OUT / n).write_text(json.dumps(v, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ranks(vals):
    return {
        k: 1 + sum(x > v for x in vals.values()) + (sum(x == v for x in vals.values()) - 1) / 2
        for k, v in vals.items()
    }


def correlation(x, y):
    keys = set(x) & set(y)
    a = ranks({k: x[k] for k in keys})
    b = ranks({k: y[k] for k in keys})
    av = statistics.mean(a.values())
    bv = statistics.mean(b.values())
    den = math.sqrt(sum((a[k] - av) ** 2 for k in keys) * sum((b[k] - bv) ** 2 for k in keys))
    return sum((a[k] - av) * (b[k] - bv) for k in keys) / den if den else None


def top(articles):
    a = [x for x in articles if x["normal_score"] is not None]
    s = sorted([x["normal_score"] for x in a], reverse=True)
    return sorted(x["id"] for x in a if x["normal_score"] >= s[min(4, len(s) - 1)]) if s else []


def jac(a, b):
    return len(set(a) & set(b)) / len(set(a) | set(b)) if set(a) | set(b) else None


def artifact_checks(doc):
    lines = doc["article_markdown"].splitlines()
    bad = []
    count = 0
    for i, line in enumerate(lines):
        if (
            line.startswith("|")
            and i + 1 < len(lines)
            and re.fullmatch(r"\s*\|[\s:|\-]+\|\s*", lines[i + 1])
        ):
            count += 1
            n = len(line.split("|")) - 2
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                actual = len(lines[j].split("|")) - 2
                if actual != n:
                    bad.append(
                        {
                            "line": j + 1,
                            "expected_columns": n,
                            "actual_columns": actual,
                            "text": lines[j],
                        }
                    )
                j += 1
    missing = [s["f_id"] for s in doc["sources"] if s["url"] not in doc["article_markdown"]]
    return {
        "table_count": count,
        "malformed_rows": bad,
        "missing_original_source_urls": missing,
        "technical_artifact_ok": count > 0 and not bad and not missing,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    summary = rd(OUT / "summary.json")
    calls = [rd(p) for p in (OUT / "calls").glob("*.json")]
    initial = [rd(p) for p in (OLD / "calls").glob("*.json")]
    preflight = {x["request_sha256"] for x in rd(OUT / "schema-amendment.json")["failed_calls"]}
    labels = rd(OUT / "control-labels.json")
    metrics = []
    docs = rd(OUT / "legacy-documents.json") + rd(OUT / "holdout-documents.json")
    audit = {d["id"]: artifact_checks(d) for d in docs}
    save("artifact-audit.json", audit)
    for row in summary["benchmarks"]:
        cohort, method = row["cohort"], row["method"]
        runs = [rd(p) for p in sorted((OUT / "benchmarks" / cohort).glob(method + "-*.json"))]
        assert len(runs) == 3
        scores = [{a["id"]: a["reference_score"] for a in r["result"]["articles"]} for r in runs]
        tops = [top(r["result"]["articles"]) for r in runs]
        cs = [
            c
            for c in calls
            if c["tag"].startswith(cohort + ":" + method + ":")
            and c["request_sha256"] not in preflight
        ]
        phase_wall = []
        for index in range(1, 4):
            phase = [c for c in cs if c["tag"].startswith(f"{cohort}:{method}:{index}")]
            ends = [datetime.fromisoformat(c["completed_at"]) for c in phase]
            if phase and all(c["latency_ms"] is not None for c in phase):
                phase_wall.append(
                    (
                        max(ends)
                        - min(
                            e - timedelta(milliseconds=c["latency_ms"])
                            for e, c in zip(ends, phase, strict=False)
                        )
                    ).total_seconds()
                )
        widths = [v["score_range"] for v in row["stability"]]
        m = {
            "cohort": cohort,
            "method": method,
            "valid_calls": len(cs),
            "cost_usd": sum(c["estimated_usd"] for c in cs),
            "phase_wall_seconds": phase_wall,
            "accepted_counts": [len(x) for x in row["accepted_sets"]],
            "mean_score_range": statistics.mean(widths),
            "max_score_range": max(widths),
            "over_10_points": sum(x > 10 for x in widths),
            "adoption_flips": sum(v["adoption_flip"] for v in row["stability"]),
            "top_five_including_ties": tops,
            "top_jaccard_same_order": jac(tops[0], tops[1]),
            "top_jaccard_shuffled": jac(tops[0], tops[2]),
            "spearman_same_order": correlation(scores[0], scores[1]),
            "spearman_shuffled": correlation(scores[0], scores[2]),
        }
        if cohort == "controls":

            def pair(r, p):
                return any(set(p) <= set(g["ids"]) for g in r["result"]["duplicates"])

            m.update(
                negative_pass_counts=[
                    sum(
                        a["id"] in labels["negative_ids"] and a["normal_score"] is not None
                        for a in r["result"]["articles"]
                    )
                    for r in runs
                ],
                exact_duplicate_detected=[pair(r, labels["exact_duplicate_pair"]) for r in runs],
                nonduplicate_overmerged=[pair(r, labels["nonduplicate_pair"]) for r in runs],
            )
        if method == "B":
            adjustments = []
            for r in runs:
                before = {
                    a["id"]: a["reference_score"]
                    for v in r["individual_results"]
                    for a in v["articles"]
                }
                adjustments.append(
                    [
                        {
                            "id": a["id"],
                            "before": before[a["id"]],
                            "after": a["reference_score"],
                            "delta": a["reference_score"] - before[a["id"]],
                            "reason": a["adjustment_reason"],
                        }
                        for a in r["result"]["articles"]
                        if a["reference_score"] != before[a["id"]]
                    ]
                )
            m["adjustments"] = adjustments
        metrics.append(m)
    save("metrics.json", metrics)
    attempts = [rd(p) for p in sorted((OUT / "generation").glob("C*.json"))]
    first = sum(x[0]["eligible"] for x in attempts)
    rescue = sum(len(x) == 2 and x[-1]["eligible"] for x in attempts)
    reject = sum(not x[-1]["eligible"] for x in attempts)
    oldcost = sum(c["estimated_usd"] for c in initial)
    failedcost = sum(c["estimated_usd"] for c in calls if c["request_sha256"] in preflight)
    total = summary["estimated_usd"] + oldcost
    save(
        "total-cost.json",
        {
            "v2": summary["estimated_usd"],
            "v2_incomplete_A_response": failedcost,
            "v1_stopped_trial": oldcost,
            "total_saved_successful_response_usd": total,
            "unrecorded_interrupted_requests": "possible; no billing reconciliation",
        },
    )

    def f(v):
        return "算出不能" if v is None else f"{v:.3f}"

    lines = [
        "# 比較記事生成・採点方式の評価結果",
        "",
        "実施日：2026-10-14。探索的なAPI比較実験。人による独立した正解ラベルとの一致評価は未実施。",
        "",
        "## 再利用と固定条件",
        "",
        "完成記事20本、原資料60件、根拠パッケージ、検証要求の本文一致、ベクトル、MMR、既存30クラスタを再利用した。記事SHA-256と原文ハッシュを検証し、以前の成果物は変更していない。20本はCodex編集を含む旧方式記事で、新方式の生成時3項目記録は欠落扱いのまま保持した。",
        "",
        "歴史的665記事のクラスタを評価に使用した。企業IDを分離した最新666記事の再クラスタリング評価ではない。PR TIMESの配信ID・原資料の来歴は維持した。",
        "",
        "生成gpt-4.1-mini-2025-04-14、検証・採点gpt-4.1-2025-04-14、temperature=0。必須3項目を生成と検証で点検。A/Bへ同じ本文・共通原文照合・100点ルーブリックを渡し、Bの全体確認にも本文全文を渡した。元順位・MMR値・以前の品質点は渡さずランダムIDで提示した。",
        "",
        "各方式3回（同順序2回・並べ替え1回）。本文の切り捨てやAの分割は行っていない。不適・未確認の通常点はnull。重大な不適の混入、既知不適通過0、少なくとも一部採用、採否安定性・品質・費用・時間の順で比較する条件を事前固定した。点数幅10点超と採否反転は調査対象。公開の品質点閾値は作っていない。",
        "",
        "## 実行上の問題",
        "",
        "v1ではモデルが引用欄に原文の言い換えを返し、原文一致検査に失敗したため採用せず保存した。v2は原資料・記事の箇所IDから正確な引用と位置を復元する方式へ修正した。引用の一致は内容の正しさ自体を保証しない。",
        "",
        "v2の最初のA応答は20本中3本しか返らなかった。完成API応答でも欠落を検出し、正式3試行から除外した。記事ごとの必須出力枠と、その記事に限定した引用IDへ修正し、最終A/Bで同じスキーマ契約を使用した。失敗応答と費用を残した。",
        "",
        "APIの分間トークン制限で429が発生。同時実行2、段階の逐次実行、通信再試行は保存ログを含め計4回まで・15秒間隔へ変更した。品質による選び直しは最大1回、計2組。APIキー・認証ヘッダーは保存していない。",
        "",
        "## 未使用クラスタでの生成・検証",
        "",
        f"10クラスタ・合計{sum(len(x) for x in attempts)}組。初回候補{first}件、選び直しによる追加候補{rescue}件、却下{reject}件。これは共通原文検証までの結果で、最終採点の採否とは異なる。",
        "",
        "|クラスタ|試した3記事組|生成→検証|共通検証後|",
        "|---|---|---|---|",
    ]
    for a in attempts:
        lines.append(
            "|"
            + a[0]["cluster"]
            + "|"
            + " → ".join("/".join(x["ids"]) for x in a)
            + "|"
            + " / ".join(
                x["normalized_generation"]["raw"]["comparison_status"]
                + "→"
                + x["document"]["common_verification"]["comparison_status"]
                for x in a
            )
            + "|"
            + ("候補" if a[-1]["eligible"] else "却下")
            + "|"
        )
    lines += [
        "",
        "C07の2組目で、生成側がeligibleとした同じ共同発表2件を別モデルが検出して却下した。既存の同一段落・原文位置・ハッシュで裏付けた追加検出1件。",
        "",
        "C07では初回理由コードdistinct_targetsが3IDを含み、選定処理がsame_targetの2IDだけを制約化したため、2組目にもF809/F876が残った。理由を選び直しへ反映する実装が不十分。3組目は実行していない。2組で却下はクラスタに比較可能な組が一切ないという証明ではない。",
        "",
        "## A/B比較",
        "",
        "上位集合は5位の同点記事も含む。Spearmanは同点平均順位。3試行から精密な信頼性は主張しない。",
        "",
        "|データ|方式|採用数|点数幅 平均/最大|採否反転|同順/並替 上位集合Jaccard|同順/並替 順位相関|呼出数|推定USD|",
        "|---|---|---|---:|---:|---|---|---:|---:|",
    ]
    for m in metrics:
        lines.append(
            "|"
            + m["cohort"]
            + "|"
            + m["method"]
            + "|"
            + "/".join(map(str, m["accepted_counts"]))
            + "|"
            + f"{m['mean_score_range']:.2f}/{m['max_score_range']}"
            + "|"
            + str(m["adoption_flips"])
            + "|"
            + f(m["top_jaccard_same_order"])
            + "/"
            + f(m["top_jaccard_shuffled"])
            + "|"
            + f(m["spearman_same_order"])
            + "/"
            + f(m["spearman_shuffled"])
            + "|"
            + str(m["valid_calls"])
            + "|"
            + f"{m['cost_usd']:.6f}"
            + "|"
        )
    lines += [
        "",
        "個別点・調整後点・理由、各軸点、採否、本文引用、重複群・代表は各試行とmetrics.jsonに保存。段階の実時間を記録し、並列API応答時間の合計と区別した。",
        "",
        "## 既知不適・重複試験",
        "",
        "C07の自然発生した原資料から共同発表を別製品とした人工本文を作り、表示なしT201と不適記録・表示ありT202を試した。T203は原資料にない97%削減・月額1円を既存記事へ追加。T204はC01記事の完全複製。T205は同じIoT分野でも違う判断目的のC26記事。人工試験例を自然発生不具合の件数に混ぜていない。",
        "",
        "|方式|不適通過（3回）|完全重複を検出（3回）|別内容を過剰統合（3回）|",
        "|---|---|---|---|",
    ]
    for m in metrics:
        if m["cohort"] == "controls":
            lines.append(
                "|"
                + m["method"]
                + "|"
                + "/".join(map(str, m["negative_pass_counts"]))
                + "|"
                + "/".join(map(str, m["exact_duplicate_detected"]))
                + "|"
                + "/".join(map(str, m["nonduplicate_overmerged"]))
                + "|"
            )
    lines += [
        "",
        "不適記録は保存・採点入力・通常点nullへの伝達を確認。表示なし例の内容検出と、表示あり例の強制除外を区別する。原文検証は生成側の結論を渡さない共通工程。",
        "",
        "## 費用",
        "",
        "使用量と公式単価による推定で請求照合ではない。実ログのキャッシュ割引を含む。構築時の2方式×3回や試験例の費用を本番1回へ置き換えない。",
        "",
        "|工程|成功応答|入力|キャッシュ入力|出力|推定USD|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for k, v in summary["usage"].items():
        lines.append(
            "|"
            + k
            + "|"
            + str(v["calls"])
            + "|"
            + str(v["input_tokens"])
            + "|"
            + str(v["cached_tokens"])
            + "|"
            + str(v["output_tokens"])
            + "|"
            + f"{v['estimated_usd']:.6f}"
            + "|"
        )
    lines += [
        "",
        f"v2合計 USD {summary['estimated_usd']:.6f}（欠落A応答 USD {failedcost:.6f}を含む）。中止したv1 USD {oldcost:.6f}。保存済み成功応答総計 USD {total:.6f}。途中中断で応答未保存の要求は集計外の可能性があり、請求額の保証ではない。",
        "",
        "生成費用はA/Bへ二重計上せず、共通原文検証と方式別採点・失敗試行を分離した。採用1本当たりの本番費用は、最終採用本数と人の原文サンプル確認が未確定のため、この実験額から断定しない。",
        "",
        "単価：[GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)、[GPT-4.1](https://developers.openai.com/api/docs/models/gpt-4.1)。",
        "",
        "",
        "",
        "判断の考察と本文サンプル点検はdecision.jsonを参照。過去のCodex点数は作成者が関与した暫定参考で、独立した人の正解にはしない。人による採否・品質との一致、全採用群の問題混入率は未確定。既知不適0件でも将来の無誤りを保証しない。",
        "",
        "方式は未確定。指示修正後のマーク付き再評価報告を最新の判断とする。サービスDB・WordPress・本番採点設定は更新していない。",
        "",
        "## 保存先",
        "",
        "- ../.local/"
        + OUT.name
        + "/：要求・応答、モデル、ハッシュ、使用量、各試行、metrics.json、検査記録",
        "- ../.local/" + OLD.name + "/：中止した引用形式v1試行",
        "- ../tools/comparison_evaluation_experiment.py：再実行スクリプト",
        "- ../tools/report_comparison_evaluation.py：オフライン集計",
        "- [元計画](comparison-generate-then-evaluate-experiment-plan-20261014.md)",
    ]
    if (OUT / "decision.json").exists():
        rd(OUT / "decision.json")
        lines[2:2] = [
            "**訂正：方式選定の主評価は、生成時の適否マーク・理由を保持した処理に限定する。** マークなしの人工複製T204は今回の条件から外す。Bを改善候補とした以前の推奨は取り下げ、A/Bの方式は未確定とする。採否の変化だけでAを不採用とせず、指示・出力設計を先に見直す。[マーク付き比較の訂正報告](comparison-generation-marked-evaluation-20261014.md)と[指示修正後の再評価](comparison-generation-marked-reevaluation-20261014.md)を参照する。以下の旧20本・人工例の数値は履歴として保持する。",
            "",
        ]
        section = [
            "## 本番方式の判断と成果物点検",
            "",
            "- A：既存20本の順序変更時の順位相関0.329、未使用7本の採用数7/7/5。C08を2回採用し、順序変更後に不適へ反転。未使用記事の最大点数幅49点。",
            "- B：既存20本の順序変更時の順位相関0.726、未使用記事の採用数6/6/6。C08を3回とも除外。ただし完全複製を見逃した試行が2/3回あり、そのまま採用できない。",
            "- 原資料にない数値、表示あり・なしの共同発表の人工不適例は両方式とも3回すべて通常採用から除外した。",
            "- 新方式で候補とした7記事のうち、4本に比較表の列数崩れ、4本に元の原資料URLの欠落があり、重なりを除くと5本。機械記録のID・URL・ハッシュは残っているが、本文の読者向け出典は不足している。モデル採点だけではこれらを止められなかった。",
            "",
            "|記事|表の列数不備|本文から欠落した原資料ID|",
            "|---|---|---|",
        ]
        for label, v in audit.items():
            if label.startswith("H"):
                section.append(
                    "|"
                    + label
                    + "|"
                    + ("あり" if v["malformed_rows"] else "なし")
                    + "|"
                    + ("/".join(v["missing_original_source_urls"]) or "なし")
                    + "|"
                )
        section += [
            "",
            "C08本文は小売店舗運営、建設の工事報告、大学研究の事業化を「業務効率化と意思決定支援」で束ねている。同じ読者の具体的な選択や共通工程設計にはなっていないとCodexが全文を点検して判断した。この編集判断は独立した人の正解ラベルとは区別する。根拠文と原資料ハッシュはeditorial-review.json。",
            "",
            "形式・原資料URL検査を通り、C08の疑義を除いた新記事はH012-0だけであり、これも最終公開承認や完全な人の事実監査は完了していない。候補1本を「新方式で問題のない記事を数本確保した成功」とは扱わない。既存20本は形式検査・原資料URL保持・モデル判定を全件通過したが、以前の人手編集を含むため新方式の成功実績に置き換えない。",
            "",
            "次の修正対象は、生成・検証における具体的な共通判断目的の判定、構造化された表のローカル描画と列数検査、原資料メタ情報からの出典描画、完全同一本文の決定的な重複除外と別表現の意味重複試験、共同発表の理由コードと2ID組の保存・選び直しへの反映。最大2組の上限は維持する。",
            "",
            "点数幅と順位相関は不適記事の参考点も含む。上位集合と採用数は通常点がnullでない記事のみ。形式・出典の事後点検による不備件数を、独立した人の事実精度や問題混入率の測定結果とはしていない。",
            "",
        ]
        index = lines.index("## 費用")
        lines[index:index] = section
    mapping = {m["id"]: m for m in rd(OUT / "private-mapping.json")}
    score_rows = []
    for cohort in ["legacy", "controls", "holdout"]:
        for method in ["A", "B"]:
            for rep in range(1, 4):
                run = rd(OUT / "benchmarks" / cohort / f"{method}-{rep}.json")
                before = {
                    a["id"]: a["reference_score"]
                    for v in run.get("individual_results", [])
                    for a in v["articles"]
                }
                for a in run["result"]["articles"]:
                    meta = mapping.get(a["id"], {})
                    score_rows.append(
                        {
                            "cohort": cohort,
                            "method": method,
                            "trial": rep,
                            "id": a["id"],
                            "cluster": meta.get("cluster", ""),
                            "topic": meta.get("topic", ""),
                            "article": meta.get("article", ""),
                            "comparison_status": a["comparison_status"],
                            "normal_score": a["normal_score"],
                            "reference_score": a["reference_score"],
                            "before_global_reference_score": before.get(a["id"]),
                            "eligibility_reason": a["eligibility_reason"],
                            "adjustment_reason": a["adjustment_reason"],
                            **{k: x["score"] for k, x in a["dimensions"].items()},
                        }
                    )
    with (OUT / "article-scores.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(score_rows[0]))
        writer.writeheader()
        writer.writerows(score_rows)
    section = [
        "## 記事別の採点結果",
        "",
        "元の記事順を採点入力に渡さず評価した後、保存済み対応表で記事名へ戻した。下記は通常点。不適は—で表示し、参考点・軸点・採否理由は[全198行のCSV](../.local/"
        + OUT.name
        + "/article-scores.csv)と各API出力に保存した。",
        "",
        "|クラスタ・記事分野|A（1/2/並替）|B（1/2/並替）|",
        "|---|---|---|",
    ]

    def trial_scores(cohort, method, label):
        values = []
        for rep in range(1, 4):
            a = next(
                a
                for a in rd(OUT / "benchmarks" / cohort / f"{method}-{rep}.json")["result"][
                    "articles"
                ]
                if a["id"] == label
            )
            values.append(str(a["normal_score"]) if a["normal_score"] is not None else "—")
        return "/".join(values)

    for label, meta in mapping.items():
        section.append(
            "|"
            + meta["cluster"]
            + " "
            + meta["topic"]
            + "|"
            + trial_scores("legacy", "A", label)
            + "|"
            + trial_scores("legacy", "B", label)
            + "|"
        )
    section += ["", "|新記事ID|A（1/2/並替）|B（1/2/並替）|", "|---|---|---|"]
    for d in rd(OUT / "holdout-documents.json"):
        section.append(
            "|"
            + d["id"]
            + "|"
            + trial_scores("holdout", "A", d["id"])
            + "|"
            + trial_scores("holdout", "B", d["id"])
            + "|"
        )
    section += [""]
    index = lines.index("## 費用")
    lines[index:index] = section
    doc = ROOT / "docs/comparison-generate-then-evaluate-experiment-results-20261014.md"
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("REPORT", str(doc), "TOTAL_USD", total)
    for m in metrics:
        print(
            m["cohort"],
            m["method"],
            "accepted",
            m["accepted_counts"],
            "spread",
            m["mean_score_range"],
            m["max_score_range"],
            "USD",
            m["cost_usd"],
        )


if __name__ == "__main__":
    main()
