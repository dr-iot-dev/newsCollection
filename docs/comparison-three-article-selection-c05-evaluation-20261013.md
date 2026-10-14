# 3記事選定案のC05限定・ローカル評価

入力データ日：2026-10-13。評価完了日時：2026-10-13T22:07:54.545015+09:00。 [提案書](comparison-three-article-selection-proposal-20261013.md)に基づく評価。

**C05のみの12記事・66ペア・220組合せを処理した。状態 `needs_review`、採用0組。OpenAI API・外部API・新規埋め込みAPIは0回。**

全所属記事を候補にし、現在のコアは3件。別クラスタ・ノイズは今回のモデル入力に含めない。C01〜C04の結果は別の保存先で保持し、一括処理終了時にSHA-256で不変を照合する。

## 実行方式

| 項目 | 内容 |
| --- | --- |
| モデル | DeepSeek-R1-14B-Q4_K:latest（Ollama 0.5.7、実体Q6_K・14.8B） |
| 固定ダイジェスト | 2c8fc88a397e2753c57dc5fadf895fa7723d8cf5958f4c3bde34b7681c79b924 |
| 接続先 | http://127.0.0.1:11434 のみ |
| 推論設定 | temperature=0、seed=42、num_ctx=8192、ネイティブraw入力 |
| 構造化 | 保存タイトル・本文全文。引用照合、失敗時は修復1回、修復不能はprocessing_failedを記録しunknownへ |
| 正規化 | 固定用途10分類・項目15種類。タイトル一覧から事前定義し、本文から支持できる用途だけ分類 |
| ペア判定 | 全ペアを最大8ペアずつ推論。主対象未確定は採用判定unknown。元判定は別フィールドに保持 |
| 初期条件 | τ=0.55、MMR重み0.75、R重み0.70／0.15／0.15、3ペア全通過・3組織／3対象・共通2項目以上・差異1項目以上 |

C03・C04と同じモデル・入力形式・採用条件を使った。用途辞書・比較項目は分野ごとに固定した。提案のLLM自由生成による正規化辞書を固定辞書へ変更しているため、分類辞書の不足による見落としは未評価。C01・C02とはモデル・辞書方式が異なる。

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。モデル要求ごとのプロンプト・スキーマと応答、版・ハッシュを保存した。

## 結果と保留理由

機械条件：`insufficient_comparable_articles`。追加品質確認：`needs_review`。

プロフィール：`{"multiple_targets": 12}`。採用用comparable：`{"unknown": 66}`。

採用制御前comparable：`{"unknown": 37, "yes": 2, "no": 27}`。主対象未確定に対する制御は66ペア。

- F021・F170・F272・F302・F399・F414・F425・F427・F445・F586・F590・F775：readyは0件、2項目未満の抽出は9件。未確定の対象や不足項目を類似度・MMRだけで補完しない。

- F021・F170・F272・F302・F399・F414・F425・F427・F445・F586・F590・F775：採用可能な主対象引用と保存比較項目の引用が本文に含まれることを確認。文字列一致は意味・分類の正しさの保証ではない。

- F021・F170・F272・F302・F399・F414・F425・F427・F445・F586・F590・F775：multiple_targetsで対象候補を示す一方、other_targetsが空。主対象を絞れない理由・残り対象が十分に記録されていない。モデルの状態を手動でreadyに変えない。

採用0組は、このローカルモデル・固定辞書・初期条件で採用を確定できなかったという結果。比較可能な3記事が存在しないことの証明ではない。

## 基準方式との比較

| 方式 | 記事 | 最低類似度 | 平均類似度 | 共通／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F425・F427・F445 | 0.590755 | 0.660601 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F302・F425・F427 | 0.690733 | 0.697199 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F302・F425・F427 | 0.690733 | 0.697199 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

高い類似度だけで対象・用途・比較項目の不明を通過させない。MMRによる順位付けは機械条件を通過した候補に限定する。

## 候補記事

| 記事 | 組織 | モデルの対象候補 | 状態 | 項目数 | 帰属確率／コア |
| --- | --- | --- | --- | --- | --- |
| [F021](https://prtimes.jp/main/html/rd/p/000000002.000155684.html) 印刷エレクトロニクス技術による世界初の「薄膜型樹液流センサ」と解析サービス「Sapflow Monitor」を正式リリース | アグリショット株式会社 | 薄膜型樹液流センサ | multiple_targets | 1 | 0.786722／— |
| [F170](https://prtimes.jp/main/html/rd/p/000000001.000180787.html) デジタルの力で浄化槽を「次世代を担う水インフラ」へ | 株式会社Nocnum | AquaLink | multiple_targets | 4 | 1.000000／— |
| [F272](https://prtimes.jp/main/html/rd/p/000000005.000168002.html) 78歳の発明家が開発、シーツの下に置くだけで排泄を検知する「おむつモニターチャイム」発売 | 株式会社エフエージェイ | おむつモニターチャイム | multiple_targets | 1 | 0.555347／— |
| [F302](https://prtimes.jp/main/html/rd/p/000000034.000034341.html) 梅雨入り目前、予告なく来る豪雨災害。全国約400ヵ所でIoTため池遠隔監視稼働中。 | 株式会社Braveridge | ため池管理システム | multiple_targets | 1 | 1.000000／— |
| [F399](https://prtimes.jp/main/html/rd/p/000000003.000116749.html) [IoT技術×樹木医の知見」により倒木事故を未然に防ぐ] | HARDWOOD株式会社 | ツリチル | multiple_targets | 1 | 0.950340／— |
| [F414](https://prtimes.jp/main/html/rd/p/000000010.000032306.html) 山留め壁の倒れを自動検知するIoTデバイス「山留めウォッチャー」で現場の省力化と安全性向上へ | CACH株式会社 | 山留めウォッチャー | multiple_targets | 1 | 0.930353／— |
| [F425](https://prtimes.jp/main/html/rd/p/000000017.000148560.html) 「減災×センシング」神戸のセンサー企業・旭光電機、防災・減災を支える2製品が一般発売 | 旭光電機株式会社 | 漏水みはり番 | multiple_targets | 1 | 1.000000／コア |
| [F427](https://prtimes.jp/main/html/rd/p/000000022.000119599.html) 新たな水田水管理省力化システムで水管理の地域格差をなくし、農業の未来をつくります。 | 株式会社ほくつう | 水まわりくん | multiple_targets | 1 | 1.000000／コア |
| [F445](https://prtimes.jp/main/html/rd/p/000000035.000165504.html) 水道管の漏水事故を未然に防ぐ！遠隔漏水監視システム「リークネッツセルラー LNL-C」を日経トレンディ1月号にPR掲載 (フジテコム株式会社) | フジテコム株式会社 | 水道管の漏水を検知・監視 | multiple_targets | 4 | 1.000000／コア |
| [F586](https://prtimes.jp/main/html/rd/p/000000005.000163490.html) 水道料金値上げの波 -「雨水を使う」という選択！節水と防災に役立つ「雨水インフラ」 | デンカアステック株式会社 | PURE EDEN | multiple_targets | 2 | 0.949743／— |
| [F590](https://prtimes.jp/main/html/rd/p/000000006.000080576.html) 消防設備点検業務を完全デジタル化！タブレットひとつで図面準備から報告書作成まで完結する「Watcher ZERO」リリース | 株式会社Bit peeps | Watcher ZERO | multiple_targets | 1 | 0.700168／— |
| [F775](https://prtimes.jp/main/html/rd/p/000000001.000183701.html) 「赤ちゃん、大丈夫かな？」をAIカメラが代わりに見守る時代へ。 | 株式会社 光サプライズ | Arenti 見守りAIカメラ Usamy | multiple_targets | 1 | 0.555347／— |

対象名の候補はモデル出力を保存したもの。未確定の状態を手動でreadyに変更していない。

## 件数・感度評価

全220組合せの機械条件通過は0件。以下は理由の重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| insufficient_comparison_axes | 220 |
| needs_review | 220 |
| no_meaningful_difference | 220 |
| similarity_below_threshold | 179 |
| unconfirmed_shared_purpose | 220 |

構造化・引用の修復4記事、未確認引用による除外7項目。修復不能なプロフィール0件、ペアバッチ0件。

| τ | MMR 0.65 | MMR 0.75 | MMR 0.85 |
| --- | --- | --- | --- |
| 0.50 | 保留 | 保留 | 保留 |
| 0.55 | 保留 | 保留 | 保留 |
| 0.60 | 保留 | 保留 | 保留 |
| 0.65 | 保留 | 保留 | 保留 |

採用条件は変更せず、保存判定から12設定を計算した。閾値変更による構造化の不足の解消は行わない。

## 検証・限界

- 保存本文入力ハッシュ、組織一意性、候補数、ベクトルの次元・有限値を検証。
- 全66ペアのコサイン類似度を独立再計算。最大差2.22e-16。
- 保存19項目の引用とreadyの主対象引用を原文照合。意味の正確さとは区別。
- 実データの入力順を逆にしても評価JSON全体が一致。選定ルール9件の共通検証を実施。
- 人の正解ラベルは未作成。正解率・誤採用率・誤除外率は算出していない。
- ペアの追加本文による意味の再判定は未実施。修復は構造・引用の検証失敗時に限る。未確定は保留。
- 単一モデル・固定辞書の試行。採用0組をモデル一般の性能や比較候補不在と解釈しない。

## 使用量

| 項目 | 値 |
| --- | --- |
| ローカルモデル要求 | 25 |
| 入力token | 61465 |
| 出力token | 12132 |
| 要求時間合計（秒） | 350.360 |
| 要求状態 | {"valid": 21, "validation_failed": 4} |
| OpenAI／外部／埋め込みAPI要求 | 0／0／0 |
| API料金（米ドル） | 0 |

GPU・電力等のローカル計算費用は金額換算していない。検証失敗した要求も使用量・応答履歴を残す。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c05-local-20261013/input-manifest.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c05-local-20261013/article-profiles.json)
- [selection-profiles.json](../.local/comparison-three-article-selection-c05-local-20261013/selection-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c05-local-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c05-local-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c05-local-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c05-local-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c05-local-20261013/selected-triplets.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c05-local-20261013/cluster-decisions.json)
- [evaluation.json](../.local/comparison-three-article-selection-c05-local-20261013/evaluation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c05-local-20261013/llm-usage.json)
- [source-review.json](../.local/comparison-three-article-selection-c05-local-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c05-local-20261013/real-validation.json)

[一括処理の設定・辞書](../.local/comparison-three-article-selection-c05-c30-local-20261013/cluster-config.json) / [処理スクリプト](../.local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py) / [全体報告書](comparison-three-article-selection-c05-c30-evaluation-20261013.md)

保存済み判定だけで再評価：

```powershell
python -X utf8 .local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py --clusters C05 --evaluate-only
```
