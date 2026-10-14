# 3記事選定案のC17限定・ローカル評価

入力データ日：2026-10-13。評価完了日時：2026-10-13T22:51:27.148352+09:00。 [提案書](comparison-three-article-selection-proposal-20261013.md)に基づく評価。

**C17のみの13記事・78ペア・286組合せを処理した。状態 `needs_review`、採用0組。OpenAI API・外部API・新規埋め込みAPIは0回。**

全所属記事を候補にし、現在のコアは3件。別クラスタ・ノイズは今回のモデル入力に含めない。C01〜C04の結果は別の保存先で保持し、一括処理終了時にSHA-256で不変を照合する。

## 実行方式

| 項目 | 内容 |
| --- | --- |
| モデル | DeepSeek-R1-14B-Q4_K:latest（Ollama 0.5.7、実体Q6_K・14.8B） |
| 固定ダイジェスト | 2c8fc88a397e2753c57dc5fadf895fa7723d8cf5958f4c3bde34b7681c79b924 |
| 接続先 | http://127.0.0.1:11434 のみ |
| 推論設定 | temperature=0、seed=42、num_ctx=8192、ネイティブraw入力 |
| 構造化 | 保存タイトル・本文全文。引用照合、失敗時は修復1回、修復不能はprocessing_failedを記録しunknownへ |
| 正規化 | 固定用途10分類・項目14種類。タイトル一覧から事前定義し、本文から支持できる用途だけ分類 |
| ペア判定 | 全ペアを最大8ペアずつ推論。主対象未確定は採用判定unknown。元判定は別フィールドに保持 |
| 初期条件 | τ=0.55、MMR重み0.75、R重み0.70／0.15／0.15、3ペア全通過・3組織／3対象・共通2項目以上・差異1項目以上 |

C03・C04と同じモデル・入力形式・採用条件を使った。用途辞書・比較項目は分野ごとに固定した。提案のLLM自由生成による正規化辞書を固定辞書へ変更しているため、分類辞書の不足による見落としは未評価。C01・C02とはモデル・辞書方式が異なる。

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。モデル要求ごとのプロンプト・スキーマと応答、版・ハッシュを保存した。

## 結果と保留理由

機械条件：`insufficient_comparable_articles`。追加品質確認：`needs_review`。

プロフィール：`{"multiple_targets": 13}`。採用用comparable：`{"unknown": 78}`。

採用制御前comparable：`{"unknown": 49, "yes": 27, "no": 2}`。主対象未確定に対する制御は78ペア。

- F076・F098・F114・F245・F253・F309・F333・F411・F420・F488・F538・F541・F882：readyは0件、2項目未満の抽出は12件。未確定の対象や不足項目を類似度・MMRだけで補完しない。

- F076・F098・F114・F245・F253・F309・F333・F411・F420・F488・F538・F541・F882：採用可能な主対象引用と保存比較項目の引用が本文に含まれることを確認。文字列一致は意味・分類の正しさの保証ではない。

- F098・F114・F245・F253・F309・F333・F411・F420・F488・F538・F541・F882：multiple_targetsで対象候補を示す一方、other_targetsが空。主対象を絞れない理由・残り対象が十分に記録されていない。モデルの状態を手動でreadyに変えない。

採用0組は、このローカルモデル・固定辞書・初期条件で採用を確定できなかったという結果。比較可能な3記事が存在しないことの証明ではない。

## 基準方式との比較

| 方式 | 記事 | 最低類似度 | 平均類似度 | 共通／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F253・F488・F538 | 0.607674 | 0.655945 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F333・F538・F541 | 0.633776 | 0.679728 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F253・F538・F541 | 0.683486 | 0.701762 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

高い類似度だけで対象・用途・比較項目の不明を通過させない。MMRによる順位付けは機械条件を通過した候補に限定する。

## 候補記事

| 記事 | 組織 | モデルの対象候補 | 状態 | 項目数 | 帰属確率／コア |
| --- | --- | --- | --- | --- | --- |
| [F076](https://prtimes.jp/main/html/rd/p/000000091.000137899.html) AGEST、フロンティアAI同様のゼロデイ脆弱性ハンティングを可能にするオンプレミス提供型セキュリティプラットフォーム「AGEST ZERO SHIELD」および、セキュリティパッチ対応後のテストを… | 株式会社AGEST | AGEST ZERO SHIELD | multiple_targets | 1 | 0.926669／— |
| [F098](https://prtimes.jp/main/html/rd/p/000000003.000189786.html) 【新プラン】Gemini経由の「社内情報漏洩」を防ぐ！Googleドライブの共有を自動統制するDriveChecker「内部共有管理プラン」正式リリース | DriveChecker株式会社 | DriveChecker内部共有管理プラン | multiple_targets | 1 | 0.990973／— |
| [F114](https://prtimes.jp/main/html/rd/p/000000025.000152916.html) AIがサイバー攻撃対応を支援する「サイバー攻撃対応ナビ」、ラックの脅威情報「JLIST®」を活用 | サイリーグホールディングス株式会社 | サイバー攻撃対応ナビ | multiple_targets | 1 | 1.000000／— |
| [F245](https://prtimes.jp/main/html/rd/p/000000365.000005271.html) AI顔認証エンジンFaceMe® SDKの新バージョン 7.9.2をリリース、新たにインジェクション攻撃検知（IAD）を搭載 | サイバーリンク株式会社 | FaceMe®_SDK_7.9.2 | multiple_targets | 1 | 1.000000／— |
| [F253](https://prtimes.jp/main/html/rd/p/000000428.000018759.html) 【イー・ガーディアン株式会社】生成AI時代の誹謗中傷・なりすまし・誤情報に、AI戦略で対応 | イー・ガーディアン株式会社 | IP悪用検知 | multiple_targets | 1 | 1.000000／コア |
| [F309](https://prtimes.jp/main/html/rd/p/000000057.000058563.html) 電話・ネット詐欺対策アプリ「Whoscall」AIによる詐欺の巧妙化・自動化が進む中『2026年 AI詐欺トレンド予想』を発表 | Whoscall株式会社 | Whoscall | multiple_targets | 0 | 0.923765／— |
| [F333](https://prtimes.jp/main/html/rd/p/000000126.000070711.html) 相次ぐサイバー攻撃や情報漏えいを背景に、中小企業のセキュリティ対策を支援。AIと専門エンジニアによる脆弱性診断を5万円から提供し、診断から改修までワンストップで対応。改修依頼時は診断費を全額値引き。 | 株式会社セルバ | AI脆弱性診断サービス | multiple_targets | 1 | 1.000000／— |
| [F411](https://prtimes.jp/main/html/rd/p/000000007.000161942.html) 攻撃者視点のリスク洗い出しで、見えない脆弱性を可視化SynX、脆弱性診断サービスが好調な滑り出し | 株式会社SynX | vulnerability_scan | multiple_targets | 1 | 0.978579／— |
| [F420](https://prtimes.jp/main/html/rd/p/000000013.000131909.html) S2W、サイバー脅威インテリジェンスソリューション「QUAXAR（クェーサー）」のASM機能を高度化 | S2W, Inc. | QUAXAR ASM | multiple_targets | 1 | 0.841906／— |
| [F488](https://prtimes.jp/main/html/rd/p/000000097.000051317.html) AeyeScan、生成AIを搭載したモバイルアプリ脆弱性診断機能をリリース | 株式会社エーアイセキュリティラボ | AeyeScan | multiple_targets | 1 | 1.000000／コア |
| [F538](https://prtimes.jp/main/html/rd/p/000000370.000009107.html) 相次ぐサイバー攻撃への不安を、具体的な点検・対策へAI利用リスクを無償で確認する『AI Security Check 2026』を先着10社に提供 | 株式会社サイバーセキュリティクラウド | AI Security Check 2026 | multiple_targets | 6 | 1.000000／コア |
| [F541](https://prtimes.jp/main/html/rd/p/000000412.000002454.html) ギブリー、「Givery AI Monitoring」を大幅アップデート。生成AIの全社利用を支えるガバナンス機能を拡充 | 株式会社ギブリー | Givery AI Monitoring | multiple_targets | 0 | 0.891141／— |
| [F882](https://prtimes.jp/main/html/rd/p/000000083.000014310.html) 録画画像解析AI「GJ-AI-trace」新登場 | 株式会社グラスフィアジャパン | GJ-AI-trace | multiple_targets | 1 | 0.914104／— |

対象名の候補はモデル出力を保存したもの。未確定の状態を手動でreadyに変更していない。

## 件数・感度評価

全286組合せの機械条件通過は0件。以下は理由の重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| insufficient_comparison_axes | 286 |
| needs_review | 286 |
| no_meaningful_difference | 285 |
| similarity_below_threshold | 194 |
| unconfirmed_shared_purpose | 286 |

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
- 全78ペアのコサイン類似度を独立再計算。最大差2.22e-16。
- 保存16項目の引用とreadyの主対象引用を原文照合。意味の正確さとは区別。
- 実データの入力順を逆にしても評価JSON全体が一致。選定ルール9件の共通検証を実施。
- 人の正解ラベルは未作成。正解率・誤採用率・誤除外率は算出していない。
- ペアの追加本文による意味の再判定は未実施。修復は構造・引用の検証失敗時に限る。未確定は保留。
- 単一モデル・固定辞書の試行。採用0組をモデル一般の性能や比較候補不在と解釈しない。

## 使用量

| 項目 | 値 |
| --- | --- |
| ローカルモデル要求 | 27 |
| 入力token | 73539 |
| 出力token | 11539 |
| 要求時間合計（秒） | 356.642 |
| 要求状態 | {"valid": 23, "validation_failed": 4} |
| OpenAI／外部／埋め込みAPI要求 | 0／0／0 |
| API料金（米ドル） | 0 |

GPU・電力等のローカル計算費用は金額換算していない。検証失敗した要求も使用量・応答履歴を残す。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c17-local-20261013/input-manifest.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c17-local-20261013/article-profiles.json)
- [selection-profiles.json](../.local/comparison-three-article-selection-c17-local-20261013/selection-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c17-local-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c17-local-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c17-local-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c17-local-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c17-local-20261013/selected-triplets.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c17-local-20261013/cluster-decisions.json)
- [evaluation.json](../.local/comparison-three-article-selection-c17-local-20261013/evaluation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c17-local-20261013/llm-usage.json)
- [source-review.json](../.local/comparison-three-article-selection-c17-local-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c17-local-20261013/real-validation.json)

[一括処理の設定・辞書](../.local/comparison-three-article-selection-c05-c30-local-20261013/cluster-config.json) / [処理スクリプト](../.local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py) / [全体報告書](comparison-three-article-selection-c05-c30-evaluation-20261013.md)

保存済み判定だけで再評価：

```powershell
python -X utf8 .local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py --clusters C17 --evaluate-only
```
