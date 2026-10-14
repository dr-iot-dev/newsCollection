# 3記事選定案のC30限定・ローカル評価

入力データ日：2026-10-13。評価完了日時：2026-10-14T00:01:03.961821+09:00。 [提案書](comparison-three-article-selection-proposal-20261013.md)に基づく評価。

**C30のみの9記事・36ペア・84組合せを処理した。状態 `needs_review`、採用0組。OpenAI API・外部API・新規埋め込みAPIは0回。**

全所属記事を候補にし、現在のコアは3件。別クラスタ・ノイズは今回のモデル入力に含めない。C01〜C04の結果は別の保存先で保持し、一括処理終了時にSHA-256で不変を照合する。

## 実行方式

| 項目 | 内容 |
| --- | --- |
| モデル | DeepSeek-R1-14B-Q4_K:latest（Ollama 0.5.7、実体Q6_K・14.8B） |
| 固定ダイジェスト | 2c8fc88a397e2753c57dc5fadf895fa7723d8cf5958f4c3bde34b7681c79b924 |
| 接続先 | http://127.0.0.1:11434 のみ |
| 推論設定 | temperature=0、seed=42、num_ctx=8192、ネイティブraw入力 |
| 構造化 | 保存タイトル・本文全文。引用照合、失敗時は修復1回、修復不能はprocessing_failedを記録しunknownへ |
| 正規化 | 固定用途9分類・項目14種類。タイトル一覧から事前定義し、本文から支持できる用途だけ分類 |
| ペア判定 | 全ペアを最大8ペアずつ推論。主対象未確定は採用判定unknown。元判定は別フィールドに保持 |
| 初期条件 | τ=0.55、MMR重み0.75、R重み0.70／0.15／0.15、3ペア全通過・3組織／3対象・共通2項目以上・差異1項目以上 |

C03・C04と同じモデル・入力形式・採用条件を使った。用途辞書・比較項目は分野ごとに固定した。提案のLLM自由生成による正規化辞書を固定辞書へ変更しているため、分類辞書の不足による見落としは未評価。C01・C02とはモデル・辞書方式が異なる。

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。モデル要求ごとのプロンプト・スキーマと応答、版・ハッシュを保存した。

## 結果と保留理由

機械条件：`insufficient_comparable_articles`。追加品質確認：`needs_review`。

プロフィール：`{"unknown": 1, "multiple_targets": 8}`。採用用comparable：`{"unknown": 36}`。

採用制御前comparable：`{"no": 6, "yes": 2, "unknown": 28}`。主対象未確定に対する制御は36ペア。

- F407・F582・F600・F726・F780・F787・F817・F844・F935：readyは0件、2項目未満の抽出は8件。未確定の対象や不足項目を類似度・MMRだけで補完しない。

- F407・F582・F600・F726・F780・F787・F817・F844・F935：採用可能な主対象引用と保存比較項目の引用が本文に含まれることを確認。文字列一致は意味・分類の正しさの保証ではない。

- F582・F600・F726・F780・F787・F817・F844・F935：multiple_targetsで対象候補を示す一方、other_targetsが空。主対象を絞れない理由・残り対象が十分に記録されていない。モデルの状態を手動でreadyに変えない。

採用0組は、このローカルモデル・固定辞書・初期条件で採用を確定できなかったという結果。比較可能な3記事が存在しないことの証明ではない。

## 基準方式との比較

| 方式 | 記事 | 最低類似度 | 平均類似度 | 共通／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F582・F600・F780 | 0.647843 | 0.659069 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F600・F726・F780 | 0.565676 | 0.660036 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F600・F726・F844 | 0.672195 | 0.694897 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

高い類似度だけで対象・用途・比較項目の不明を通過させない。MMRによる順位付けは機械条件を通過した候補に限定する。

## 候補記事

| 記事 | 組織 | モデルの対象候補 | 状態 | 項目数 | 帰属確率／コア |
| --- | --- | --- | --- | --- | --- |
| [F407](https://prtimes.jp/main/html/rd/p/000000007.000073133.html) 歯科エックス線画像を用いた「お口年齢AI」の開発について | 医療法人社団　葵会　AOI国際病院 | お口年齢AI | unknown | 1 | 0.891513／— |
| [F582](https://prtimes.jp/main/html/rd/p/000000002.000191154.html) 歯科医院の集患におけるAI検索表示を無料診断「DENT SHIFT」正式リリース | エムコレクションジャパン合同会社 | DENT_SHIFT | multiple_targets | 1 | 1.000000／コア |
| [F600](https://prtimes.jp/main/html/rd/p/000000012.000169742.html) 『Apollo AI』が医療法人永井病院で大きな業務改革を実現──電子カルテ MI・RA・Is（株式会社シーエスアイ） × AIエージェントの、生成AI活用の基幹システム | 株式会社Albatrus | Apollo AI | multiple_targets | 1 | 1.000000／コア |
| [F726](https://prtimes.jp/main/html/rd/p/000000266.000018629.html) テラデータ、医療・保険分野におけるAI活用と疾病予測などの成果を発表 | 日本テラデータ株式会社 | Teradata AI Services | multiple_targets | 1 | 0.858072／— |
| [F780](https://prtimes.jp/main/html/rd/p/000000002.000183085.html) PreMed、医療機関向けAIネイティブ予約システム「Galapagos」を自社開発。患者はLINEトークだけで予約が完結し、管理画面の細かな設定までAIエージェントで実行 | PreMed株式会社 | Galapagos | multiple_targets | 0 | 1.000000／コア |
| [F787](https://prtimes.jp/main/html/rd/p/000000004.000113577.html) 口コミ100件、もう全部読まなくていい。AIが「比較する3院」まで絞る「AIクリニックセレクト」 | エアビジョン株式会社 | AIクリニックセレクト | multiple_targets | 1 | 1.000000／— |
| [F817](https://prtimes.jp/main/html/rd/p/000000021.000172103.html) Verbex、SCOグループの歯科医院向けオールインワンプラットフォーム「paylight X」「AIでんわ」に音声対話AI基盤を提供 | 株式会社Verbex | Verbexの音声対話AI基盤 | multiple_targets | 1 | 0.741836／— |
| [F844](https://prtimes.jp/main/html/rd/p/000000040.000016841.html) シェアメディカル、医療AIを安全に実行するための「医療AIハーネス」MediLine Engineを発表 | 株式会社シェアメディカル | MediLine Engine | multiple_targets | 6 | 1.000000／— |
| [F935](https://prtimes.jp/main/html/rd/p/000000179.000043855.html) AI献立・栄養管理アプリ『おいしい健康』AI栄養ロボット「ぴたこん」が食事に伴走・アドバイス | 株式会社おいしい健康 | nutrition_coaching | multiple_targets | 1 | 0.553281／— |

対象名の候補はモデル出力を保存したもの。未確定の状態を手動でreadyに変更していない。

## 件数・感度評価

全84組合せの機械条件通過は0件。以下は理由の重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| insufficient_comparison_axes | 84 |
| needs_review | 84 |
| no_meaningful_difference | 84 |
| similarity_below_threshold | 39 |
| unconfirmed_shared_purpose | 84 |

構造化・引用の修復3記事、未確認引用による除外1項目。修復不能なプロフィール0件、ペアバッチ0件。

| τ | MMR 0.65 | MMR 0.75 | MMR 0.85 |
| --- | --- | --- | --- |
| 0.50 | 保留 | 保留 | 保留 |
| 0.55 | 保留 | 保留 | 保留 |
| 0.60 | 保留 | 保留 | 保留 |
| 0.65 | 保留 | 保留 | 保留 |

採用条件は変更せず、保存判定から12設定を計算した。閾値変更による構造化の不足の解消は行わない。

## 検証・限界

- 保存本文入力ハッシュ、組織一意性、候補数、ベクトルの次元・有限値を検証。
- 全36ペアのコサイン類似度を独立再計算。最大差2.22e-16。
- 保存13項目の引用とreadyの主対象引用を原文照合。意味の正確さとは区別。
- 実データの入力順を逆にしても評価JSON全体が一致。選定ルール9件の共通検証を実施。
- 人の正解ラベルは未作成。正解率・誤採用率・誤除外率は算出していない。
- ペアの追加本文による意味の再判定は未実施。修復は構造・引用の検証失敗時に限る。未確定は保留。
- 単一モデル・固定辞書の試行。採用0組をモデル一般の性能や比較候補不在と解釈しない。

## 使用量

| 項目 | 値 |
| --- | --- |
| ローカルモデル要求 | 17 |
| 入力token | 51640 |
| 出力token | 6971 |
| 要求時間合計（秒） | 222.031 |
| 要求状態 | {"valid": 14, "validation_failed": 3} |
| OpenAI／外部／埋め込みAPI要求 | 0／0／0 |
| API料金（米ドル） | 0 |

GPU・電力等のローカル計算費用は金額換算していない。検証失敗した要求も使用量・応答履歴を残す。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c30-local-20261013/input-manifest.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c30-local-20261013/article-profiles.json)
- [selection-profiles.json](../.local/comparison-three-article-selection-c30-local-20261013/selection-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c30-local-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c30-local-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c30-local-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c30-local-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c30-local-20261013/selected-triplets.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c30-local-20261013/cluster-decisions.json)
- [evaluation.json](../.local/comparison-three-article-selection-c30-local-20261013/evaluation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c30-local-20261013/llm-usage.json)
- [source-review.json](../.local/comparison-three-article-selection-c30-local-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c30-local-20261013/real-validation.json)

[一括処理の設定・辞書](../.local/comparison-three-article-selection-c05-c30-local-20261013/cluster-config.json) / [処理スクリプト](../.local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py) / [全体報告書](comparison-three-article-selection-c05-c30-evaluation-20261013.md)

保存済み判定だけで再評価：

```powershell
python -X utf8 .local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py --clusters C30 --evaluate-only
```
