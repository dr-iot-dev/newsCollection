# 新しいKによるPR TIMES資料選択・後続ステップ評価（2026-10-11）

距離順に10ペアを試行完了したが、条件を満たす3資料は成立しなかった。

## 引き継いだ条件

- 継続実行ID：`37258cef-a20f-41d0-965f-7abcc293459c`。元実行：`24709c1c-d4b2-41ee-bf63-b08629eacbb6`。修正したペア計画の指示を別fingerprintで記録し、初期資料・K・収集結果・ベクトル・距離を完全一致で引き継いだ。
- カテゴリ：生成AI。初期10資料と[再抽出した11語のK](comparison-category-keywords-evaluation-20261011.md)は完全一致を確認して保持。
- 資料群A上限：100件。今回は以前の10資料スモーク評価の上限を流用していない。
- 計画：距離順に最大10ペア。同じペアの群B候補を使い切ってから次ペアへ進む。10ペア未完了の中断を探索不成立へ変換しない。
- 生成／特徴抽出／独立検証の設定：gpt-5.2 / gpt-4.1 / gpt-5.1。埋め込み：text-embedding-3-small。

## 収集・距離・検証の結果

- 状態：`exhausted`。理由：`ten_pairs_completed_without_comparison`。
- ネイティブ検索式：166件。明示的な0件を確認した404：141件。
- 候補ページ確認：148件。採否内訳：`{"category_or_source_ineligible": 73, "fewer_than_three_keywords": 58, "accepted": 17}`。
- 資料群A：17件。全ペア距離：136件。
- 埋め込み呼出し：29回、入力トークン合計：46289。
- ペア試行完了：10件。第三資料試行：0件。
- K確定後のAI実行記録：22件。実行全体のAI呼出し：33回、外部呼出し：441回。API未到達や無効応答も回数へ含む。別途、0件404確認の診断GETを3回実行した。

PR TIMESの公開検索は各式の最初のページを利用しており、全検索ページの網羅取得ではない。終了理由は `planned_native_queries_finished`、ページ方針は `first_page_per_query`。100件は採用上限であり、100件の取得保証ではない。

無関係なURL・連絡先を除外した本文全体を分割して埋め込みを計算し、全ベクトルの生成後にコサイン距離を保存した。除外範囲、分割、入力hash、モデル・次元・ベクトルも監査に残す。

## ペア試行

今回の10ペアはいずれもステップ6で比較不可と判定された。1位は同一製品の機能の提供予定・提供開始の告知、2〜10位はLLMO計測を使った調査だが、工務店・ブランド買取・不用品回収など選定目的が異なる業界を扱うため、同じ用途で選ぶ代替候補にならなかった。群B抽出、第三資料の選択、3資料の項目別充足・独立検証（ステップ7〜10）は実施対象となるペアがなく未実施。未完了AI応答をペア不合格へ数えることなく、10ペアの判定完了をもって終了した。

| 順位 | 左資料ID | 右資料ID | 距離 | 群B件数 | 第三資料試行 | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | a99eec12-b15d-41bc-bb03-bcd2699881b2 | e4390f10-96dd-4a19-97fa-a0fd363f2bfe | 0.02451833 | 未抽出 | 0 | 比較ペア不成立 |
| 2 | 0e340da9-a778-45f8-966f-4fe25669884d | 88612f09-ee51-4c84-90d7-0c606c1884a9 | 0.05679051 | 未抽出 | 0 | 比較ペア不成立 |
| 3 | 001a2ca8-3ddc-4d6d-9ee5-d3e11211b445 | 7374002f-d7c5-4e3e-9ff1-4b42361aef18 | 0.06302547 | 未抽出 | 0 | 比較ペア不成立 |
| 4 | 04fdb199-105f-4665-958a-520914d76525 | 0e340da9-a778-45f8-966f-4fe25669884d | 0.06485095 | 未抽出 | 0 | 比較ペア不成立 |
| 5 | 001a2ca8-3ddc-4d6d-9ee5-d3e11211b445 | 0e340da9-a778-45f8-966f-4fe25669884d | 0.07329397 | 未抽出 | 0 | 比較ペア不成立 |
| 6 | 0e340da9-a778-45f8-966f-4fe25669884d | 16b91e01-6c0a-4385-a699-672b20a16440 | 0.07639918 | 未抽出 | 0 | 比較ペア不成立 |
| 7 | 0e340da9-a778-45f8-966f-4fe25669884d | 7374002f-d7c5-4e3e-9ff1-4b42361aef18 | 0.07640806 | 未抽出 | 0 | 比較ペア不成立 |
| 8 | 001a2ca8-3ddc-4d6d-9ee5-d3e11211b445 | 04fdb199-105f-4665-958a-520914d76525 | 0.07736679 | 未抽出 | 0 | 比較ペア不成立 |
| 9 | 04fdb199-105f-4665-958a-520914d76525 | 7374002f-d7c5-4e3e-9ff1-4b42361aef18 | 0.07892223 | 未抽出 | 0 | 比較ペア不成立 |
| 10 | 001a2ca8-3ddc-4d6d-9ee5-d3e11211b445 | 88612f09-ee51-4c84-90d7-0c606c1884a9 | 0.08467019 | 未抽出 | 0 | 比較ペア不成立 |

## 資料群A

| 資料ID | K一致数 | 出典 |
| --- | --- | --- |
| e4390f10-96dd-4a19-97fa-a0fd363f2bfe | 4 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000418.000073671.html) |
| 001a2ca8-3ddc-4d6d-9ee5-d3e11211b445 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000010.000155520.html) |
| 7374002f-d7c5-4e3e-9ff1-4b42361aef18 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000009.000155520.html) |
| f3f1f17e-b5a1-4e90-9c55-e9b93fd6dee7 | 4 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000049.000124664.html) |
| 490f749e-39e7-41ff-b345-cd23c84d5485 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000389.000073671.html) |
| 59227272-3599-4c05-b436-7e9bd5e428dd | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000378.000073671.html) |
| fa14dce8-85d6-4269-b7d4-f0d079a72543 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000068.000019103.html) |
| 713ebca7-5f9a-4d0b-9957-4a5b3a332c9c | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000193.000121022.html) |
| 1f10944d-42dc-4f42-8151-1781099a2f2d | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000072.000118521.html) |
| a99eec12-b15d-41bc-bb03-bcd2699881b2 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000395.000073671.html) |
| 4c42b340-15ba-4ffb-b63f-bd867263e6d8 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000004.000155520.html) |
| 16b91e01-6c0a-4385-a699-672b20a16440 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000008.000155520.html) |
| 88612f09-ee51-4c84-90d7-0c606c1884a9 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000007.000155520.html) |
| 0e340da9-a778-45f8-966f-4fe25669884d | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000006.000155520.html) |
| 04fdb199-105f-4665-958a-520914d76525 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000005.000155520.html) |
| adfe0541-102c-41ef-8c9b-ae9f16cb2afd | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000003.000155520.html) |
| b9951bc9-e0d7-4577-bd9d-a1ec21d5f5e9 | 3 | [PR TIMES](https://prtimes.jp/main/html/rd/p/000000002.000155520.html) |

## 修正・検証

途中でPR TIMESの0件検索がHTTP 404を返すことを確認した。検索式と一致するタイトル、0件表示、明示的な該当なし案内を原文で確認できる場合だけ、0件として保存して次へ進むよう修正した。その他の404・通信失敗・未完了AI応答は不合格ペアへ数えない。取得・探索・Web収集の関連124件の回帰試験、ruff・mypy（120ファイル）が通過した。

最初のペアでAIが製品名へ機能・提供状態を付け足し、比較項目へ原文にない説明表現を使ったため、原文照合に失敗した。`pair_plan-v2` / `pair_cells-v2` で名称と検索語を原文からそのまま選ぶ指示、同一製品の予定・提供開始告知を別製品にしない指示を強化した。元実行の23回のAI履歴を保持し、初期資料・K・検索・埋め込みを再実行せず、ペア探索から継続した。改訂後の探索・AI診断の関連82件の回帰試験も通過した。

比較記事の選択条件は3項目以上、それぞれ2/3資料以上の原文根拠と独立検証である。今回の結果は資料選択の結果であり、WordPressへの送信は実行していない。

## 保存先

- [監査JSON](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/audit.json)：工程、ID・件数、K、本文・版、距離、比較項目、群B、全試行・採否・根拠。
- [修正前の監査JSON](../.local/pair-genai-new-k-downstream-20261011/24709c1c-d4b2-41ee-bf63-b08629eacbb6/audit.json)：166検索式・収集17資料・136距離・未成立のAI計画と履歴。検索・収集の工程記録はこちらへ保持し、継続実行には引継ぎhashを保存。
- [資料群A一覧](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/group-a.csv)、[検索履歴](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/native-searches.csv)。
- [全ペア距離](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/pair-distances.csv)、[第三資料の距離](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/third-distances.csv)、[項目別充足](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/coverage.csv)。
- [ペア判定の詳細](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/pair-decisions.csv)：比較目的・項目・製品・AIの判断理由・第三資料の判定。
- [AI実行記録](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/ai-runs.json)、[概要](../.local/pair-genai-new-k-downstream-20261011/37258cef-a20f-41d0-965f-7abcc293459c/summary.json)。
