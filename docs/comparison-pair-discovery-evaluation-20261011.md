# 生成AIカテゴリのPR TIMESペア探索・実資料評価（2026-10-11）

newsWeaveの新しい資料選択を公開サイト・実AI・実埋め込みで評価した。10資料の試験実行は、距離順の10ペアをすべて不適合と判定して探索不成立で終了した。比較記事用の3資料は採用していない。

## 対象・設定

- 実行ID: d68ce534-7b5f-4f40-9de7-d8cefcb761bf
- カテゴリ: [PR TIMES 生成AI](https://prtimes.jp/topics/keywords/%E7%94%9F%E6%88%90AI)
- 初期資料: 10件。実サイトから取得した原文・資料版を固定して再利用。
- 今回の群A上限: 10件。通常の実装既定値は100件であり、実100資料の品質評価とは区別する。
- 生成モデル: gpt-5.2。独立検証用はgpt-5.1、特徴抽出用はgpt-4.1を設定。
- 埋め込み: text-embedding-3-small / 1,536次元。本文全体を分割し、加重平均して正規化。
- 本番と分けたPostgreSQLスキーマで実行。公開・下書き送信・既存記事の更新は実行していない。

## 結果

- 群A: 10資料。全ペア距離: 45件。
- 埋め込み呼出し: 15回、入力トークン合計: 22,668。
- 完了ペア: 10/10。状態: exhausted。
- 今回の新規AI生成: 15回（カテゴリ修正とペア計画の修正を含む）。外部呼出し合計: 69回。
- 初期資料の特徴語抽出10回は、入力hash・モデル・指示版が一致する実AI履歴を再利用した。費用単価未設定のため金額は不明。
- 取得ページ上限から複数回再開し、群Aの採用候補5件→8件→10件へ進んだ。確定したベクトル・完了ペアは再計算していない。
- 応答の根拠検証に失敗した箇所はwaiting_retryとして保存し、未完了ペアを失敗ペアへ数えずに再開した。

当時の検索特徴語: 生成AI、AIエージェント、要件定義、判断、社内資料、質問、スライド、LP、配置、定点調査、LLMO計測ツール。

このKはカテゴリ名・汎用語を含むため、ユーザー指摘を受けた後の新規探索には使わない。カテゴリ内の技術・機能を区別する抽出へ修正した[新しいKの評価記録](comparison-category-keywords-evaluation-20261011.md)を参照。この記録の距離・10ペア判定は、旧Kによる実行の履歴として保持する。

## 距離順に試した10ペア

| 順位 | 左資料ID | 右資料ID | 距離 | 判定 |
| --- | --- | --- | --- | --- |
| 1 | 001a2ca8-3ddc-4d6d-9ee5-d3e11211b445 | 7374002f-d7c5-4e3e-9ff1-4b42361aef18 | 0.06302547 | pair_not_comparable_or_axes_insufficient |
| 2 | 001a2ca8-3ddc-4d6d-9ee5-d3e11211b445 | 2b27e966-34c1-4204-8913-ca53f6e69995 | 0.36073330 | pair_not_comparable_or_axes_insufficient |
| 3 | 8991ca33-b989-475f-9973-68facc1bc149 | ff636996-e8cd-4b91-941e-89f647714467 | 0.36862467 | pair_not_comparable_or_axes_insufficient |
| 4 | 2b27e966-34c1-4204-8913-ca53f6e69995 | 7374002f-d7c5-4e3e-9ff1-4b42361aef18 | 0.38903428 | pair_products_not_distinct |
| 5 | cd8ade22-630a-47c1-8524-eef4277e7e79 | ff636996-e8cd-4b91-941e-89f647714467 | 0.39515236 | pair_products_not_distinct |
| 6 | 02e92921-0b60-436c-ad11-9cdbb5732f2b | 7374002f-d7c5-4e3e-9ff1-4b42361aef18 | 0.39691823 | pair_products_not_distinct |
| 7 | e4390f10-96dd-4a19-97fa-a0fd363f2bfe | f3f1f17e-b5a1-4e90-9c55-e9b93fd6dee7 | 0.40125919 | pair_products_not_distinct |
| 8 | cd8ade22-630a-47c1-8524-eef4277e7e79 | f3f1f17e-b5a1-4e90-9c55-e9b93fd6dee7 | 0.41024842 | pair_products_not_distinct |
| 9 | 02e92921-0b60-436c-ad11-9cdbb5732f2b | f3f1f17e-b5a1-4e90-9c55-e9b93fd6dee7 | 0.41232021 | pair_products_not_distinct |
| 10 | cd8ade22-630a-47c1-8524-eef4277e7e79 | e4390f10-96dd-4a19-97fa-a0fd363f2bfe | 0.41619777 | pair_products_not_distinct |

上表は実行時の記録値を保持している。7件の `pair_products_not_distinct` は、比較不適合の計画から未採用の対象欄を空にした際の理由分類によるもので、同一製品の重複を7件確認したという意味ではない。最終コードでは比較不適合を先に分類するよう修正し、試験で確認した。10ペア不合格という結果・距離・順序は変わらない。

各ペアの説明・抽出項目・根拠・AI実行IDはローカル監査に保存した。初期・検索資料にはセミナー、調査、相談支援など異なる役割が含まれる。今回の10ペアでは、比較可能なペアと3項目を併せて確認する条件を満たさなかった。

群B・第三資料の選択・3資料の独立検証へ進んだ実試行は0件である。この分岐、2/3資料の根拠、第三資料の順次再試行は模擬応答とSQLite/PostgreSQLの試験で確認した。実資料での比較記事成立、実100資料の品質評価、記事生成への接続は未完了である。

## 記録

- [監査JSON](../.local/pair-genai-evaluation-20261011/d68ce534-7b5f-4f40-9de7-d8cefcb761bf/audit.json)
- [全ペア距離CSV](../.local/pair-genai-evaluation-20261011/d68ce534-7b5f-4f40-9de7-d8cefcb761bf/pair-distances.csv)
- [工程レポート](../.local/pair-genai-evaluation-20261011/d68ce534-7b5f-4f40-9de7-d8cefcb761bf/report.md)
- [AI履歴](../.local/pair-genai-evaluation-20261011/d68ce534-7b5f-4f40-9de7-d8cefcb761bf/ai-runs.json)

ローカル監査は原文を含むためGitの対象外。試行中に修正した旧版の結果も実行ID別に保持し、合格結果と混ぜない。
