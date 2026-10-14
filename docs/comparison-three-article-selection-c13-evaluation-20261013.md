# 3記事選定案のC13限定・ローカル評価

入力データ日：2026-10-13。評価完了日時：2026-10-13T22:40:19.821467+09:00。 [提案書](comparison-three-article-selection-proposal-20261013.md)に基づく評価。

**C13のみの9記事・36ペア・84組合せを処理した。状態 `needs_review`、採用0組。OpenAI API・外部API・新規埋め込みAPIは0回。**

全所属記事を候補にし、現在のコアは1件。別クラスタ・ノイズは今回のモデル入力に含めない。C01〜C04の結果は別の保存先で保持し、一括処理終了時にSHA-256で不変を照合する。

## 実行方式

| 項目 | 内容 |
| --- | --- |
| モデル | DeepSeek-R1-14B-Q4_K:latest（Ollama 0.5.7、実体Q6_K・14.8B） |
| 固定ダイジェスト | 2c8fc88a397e2753c57dc5fadf895fa7723d8cf5958f4c3bde34b7681c79b924 |
| 接続先 | http://127.0.0.1:11434 のみ |
| 推論設定 | temperature=0、seed=42、num_ctx=8192、ネイティブraw入力 |
| 構造化 | 保存タイトル・本文全文。引用照合、失敗時は修復1回、修復不能はprocessing_failedを記録しunknownへ |
| 正規化 | 固定用途8分類・項目14種類。タイトル一覧から事前定義し、本文から支持できる用途だけ分類 |
| ペア判定 | 全ペアを最大8ペアずつ推論。主対象未確定は採用判定unknown。元判定は別フィールドに保持 |
| 初期条件 | τ=0.55、MMR重み0.75、R重み0.70／0.15／0.15、3ペア全通過・3組織／3対象・共通2項目以上・差異1項目以上 |

C03・C04と同じモデル・入力形式・採用条件を使った。用途辞書・比較項目は分野ごとに固定した。提案のLLM自由生成による正規化辞書を固定辞書へ変更しているため、分類辞書の不足による見落としは未評価。C01・C02とはモデル・辞書方式が異なる。

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。モデル要求ごとのプロンプト・スキーマと応答、版・ハッシュを保存した。

## 結果と保留理由

機械条件：`insufficient_comparable_articles`。追加品質確認：`needs_review`。

プロフィール：`{"multiple_targets": 9}`。採用用comparable：`{"unknown": 36}`。

採用制御前comparable：`{"no": 5, "unknown": 21, "yes": 10}`。主対象未確定に対する制御は36ペア。

- F065・F438・F524・F592・F608・F637・F795・F893・F908：readyは0件、2項目未満の抽出は9件。未確定の対象や不足項目を類似度・MMRだけで補完しない。

- F065・F438・F524・F592・F608・F637・F795・F893・F908：採用可能な主対象引用と保存比較項目の引用が本文に含まれることを確認。文字列一致は意味・分類の正しさの保証ではない。

- F065・F438・F524・F592・F608・F637・F795・F893・F908：multiple_targetsで対象候補を示す一方、other_targetsが空。主対象を絞れない理由・残り対象が十分に記録されていない。モデルの状態を手動でreadyに変えない。

採用0組は、このローカルモデル・固定辞書・初期条件で採用を確定できなかったという結果。比較可能な3記事が存在しないことの証明ではない。

## 基準方式との比較

| 方式 | 記事 | 最低類似度 | 平均類似度 | 共通／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F065・F438・F637 | 0.697849 | 0.716232 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F065・F438・F637 | 0.697849 | 0.716232 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F065・F438・F637 | 0.697849 | 0.716232 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

高い類似度だけで対象・用途・比較項目の不明を通過させない。MMRによる順位付けは機械条件を通過した候補に限定する。

## 候補記事

| 記事 | 組織 | モデルの対象候補 | 状態 | 項目数 | 帰属確率／コア |
| --- | --- | --- | --- | --- | --- |
| [F065](https://prtimes.jp/main/html/rd/p/000000046.000113384.html) Facilo、AI駆動の3プロダクトを新規リリース | 株式会社Facilo | AI駆動CRM | multiple_targets | 1 | 0.982160／— |
| [F438](https://prtimes.jp/main/html/rd/p/000000031.000022104.html) 物件図面から簡単に登録。不動産関連情報の読み取り精度をとことん磨き上げた「不動産専用AI-OCR」をリリース | DataBee株式会社 | real_estate_ocr | multiple_targets | 0 | 1.000000／コア |
| [F524](https://prtimes.jp/main/html/rd/p/000000245.000016248.html) ＜Airbnb 2026秋季アップデート＞ | Airbnb Japan株式会社 | multiple_targets | multiple_targets | 1 | 1.000000／— |
| [F592](https://prtimes.jp/main/html/rd/p/000000006.000183890.html) 210室を保有し約100室を自主管理する不動産会社が、賃貸管理システムを内製しました。 | ウルスタ株式会社 | ウルスタくん | multiple_targets | 1 | 0.651762／— |
| [F608](https://prtimes.jp/main/html/rd/p/000000019.000136146.html) 手描きの間取り図だけで、リアルな内観CGを生成 ― Make House、住宅特化のパース生成AI『AI real CG』に新機能搭載 | Make House株式会社 | AI real CG 3D機能 | multiple_targets | 1 | 1.000000／— |
| [F637](https://prtimes.jp/main/html/rd/p/000000053.000046040.html) 不動産Vertical AI/SaaS「カナリークラウド」、物件入稿をAIが支援する「AIコンバーター」をリリース | 株式会社カナリー | AIコンバーター | multiple_targets | 1 | 0.982160／— |
| [F795](https://prtimes.jp/main/html/rd/p/000000007.000179933.html) AIが落とし物の特徴を自動抽出！遺失物管理システム「MONODOKO」にAI登録補助機能を追加 | 株式会社ＪＲ東日本情報システム | MONODOKO | multiple_targets | 1 | 0.975190／— |
| [F893](https://prtimes.jp/main/html/rd/p/000000090.000121749.html) 候補物件のアップロードが可能に！実際の物件の利回りが可視化できるようにしました。『民泊BOX』に候補物件反映機能を追加 | 株式会社Emposy | minpaku-box | multiple_targets | 1 | 1.000000／— |
| [F908](https://prtimes.jp/main/html/rd/p/000000120.000036279.html) 図面の帯替えを自動化！「AI自動マイソク帯替え機能」を10月8日にリリース | 株式会社博士.com | AI自動マイソク帯替え機能 | multiple_targets | 1 | 1.000000／— |

対象名の候補はモデル出力を保存したもの。未確定の状態を手動でreadyに変更していない。

## 件数・感度評価

全84組合せの機械条件通過は0件。以下は理由の重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| insufficient_comparison_axes | 84 |
| needs_review | 84 |
| no_meaningful_difference | 84 |
| similarity_below_threshold | 57 |
| unconfirmed_shared_purpose | 84 |

構造化・引用の修復2記事、未確認引用による除外1項目。修復不能なプロフィール0件、ペアバッチ0件。

| τ | MMR 0.65 | MMR 0.75 | MMR 0.85 |
| --- | --- | --- | --- |
| 0.50 | 保留 | 保留 | 保留 |
| 0.55 | 保留 | 保留 | 保留 |
| 0.60 | 保留 | 保留 | 保留 |
| 0.65 | 保留 | 保留 | 保留 |

採用条件は変更せず、保存判定から12設定を計算した。閾値変更による構造化の不足の解消は行わない。

## 検証・限界

- 保存本文入力ハッシュ、組織一意性、候補数、ベクトルの次元・有限値を検証。
- 全36ペアのコサイン類似度を独立再計算。最大差3.33e-16。
- 保存8項目の引用とreadyの主対象引用を原文照合。意味の正確さとは区別。
- 実データの入力順を逆にしても評価JSON全体が一致。選定ルール9件の共通検証を実施。
- 人の正解ラベルは未作成。正解率・誤採用率・誤除外率は算出していない。
- ペアの追加本文による意味の再判定は未実施。修復は構造・引用の検証失敗時に限る。未確定は保留。
- 単一モデル・固定辞書の試行。採用0組をモデル一般の性能や比較候補不在と解釈しない。

## 使用量

| 項目 | 値 |
| --- | --- |
| ローカルモデル要求 | 16 |
| 入力token | 41977 |
| 出力token | 5294 |
| 要求時間合計（秒） | 171.376 |
| 要求状態 | {"valid": 14, "validation_failed": 2} |
| OpenAI／外部／埋め込みAPI要求 | 0／0／0 |
| API料金（米ドル） | 0 |

GPU・電力等のローカル計算費用は金額換算していない。検証失敗した要求も使用量・応答履歴を残す。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c13-local-20261013/input-manifest.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c13-local-20261013/article-profiles.json)
- [selection-profiles.json](../.local/comparison-three-article-selection-c13-local-20261013/selection-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c13-local-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c13-local-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c13-local-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c13-local-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c13-local-20261013/selected-triplets.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c13-local-20261013/cluster-decisions.json)
- [evaluation.json](../.local/comparison-three-article-selection-c13-local-20261013/evaluation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c13-local-20261013/llm-usage.json)
- [source-review.json](../.local/comparison-three-article-selection-c13-local-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c13-local-20261013/real-validation.json)

[一括処理の設定・辞書](../.local/comparison-three-article-selection-c05-c30-local-20261013/cluster-config.json) / [処理スクリプト](../.local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py) / [全体報告書](comparison-three-article-selection-c05-c30-evaluation-20261013.md)

保存済み判定だけで再評価：

```powershell
python -X utf8 .local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py --clusters C13 --evaluate-only
```
