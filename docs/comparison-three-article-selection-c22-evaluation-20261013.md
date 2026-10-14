# 3記事選定案のC22限定・ローカル評価

入力データ日：2026-10-13。評価完了日時：2026-10-13T23:31:18.613063+09:00。 [提案書](comparison-three-article-selection-proposal-20261013.md)に基づく評価。

**C22のみの16記事・120ペア・560組合せを処理した。状態 `needs_review`、採用0組。OpenAI API・外部API・新規埋め込みAPIは0回。**

全所属記事を候補にし、現在のコアは1件。別クラスタ・ノイズは今回のモデル入力に含めない。C01〜C04の結果は別の保存先で保持し、一括処理終了時にSHA-256で不変を照合する。

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

プロフィール：`{"unknown": 3, "multiple_targets": 13}`。採用用comparable：`{"unknown": 120}`。

採用制御前comparable：`{"unknown": 81, "yes": 27, "no": 12}`。主対象未確定に対する制御は120ペア。

- F146・F185・F238・F255・F444・F512・F622・F673・F675・F730・F737・F825・F831・F866・F903・F961：readyは0件、2項目未満の抽出は16件。未確定の対象や不足項目を類似度・MMRだけで補完しない。

- F146・F185・F238・F255・F444・F512・F622・F673・F675・F730・F737・F825・F831・F866・F903・F961：採用可能な主対象引用と保存比較項目の引用が本文に含まれることを確認。文字列一致は意味・分類の正しさの保証ではない。

- F185・F255・F444・F512・F673・F675・F730・F825・F831・F866・F903・F961：multiple_targetsで対象候補を示す一方、other_targetsが空。主対象を絞れない理由・残り対象が十分に記録されていない。モデルの状態を手動でreadyに変えない。

採用0組は、このローカルモデル・固定辞書・初期条件で採用を確定できなかったという結果。比較可能な3記事が存在しないことの証明ではない。

## 基準方式との比較

| 方式 | 記事 | 最低類似度 | 平均類似度 | 共通／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F675・F730・F903 | 0.709553 | 0.720429 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F675・F730・F903 | 0.709553 | 0.720429 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F675・F730・F903 | 0.709553 | 0.720429 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

高い類似度だけで対象・用途・比較項目の不明を通過させない。MMRによる順位付けは機械条件を通過した候補に限定する。

## 候補記事

| 記事 | 組織 | モデルの対象候補 | 状態 | 項目数 | 帰属確率／コア |
| --- | --- | --- | --- | --- | --- |
| [F146](https://prtimes.jp/main/html/rd/p/000000154.000010477.html) KING OF TIME、問い合わせ時に選択する項目の迷いと手間を削減へ | 株式会社ヒューマンテクノロジーズ | multiple_targets | unknown | 0 | 0.994545／— |
| [F185](https://prtimes.jp/main/html/rd/p/000000016.000154056.html) BAKUTAN、三菱電機のグローバル人財情報基盤に「BAKUTAN OS」を提供 ― 形式の異なるグループ各社人財データをAIエージェントで束ね、戦略人事の実行力向上に向けて協働 | BAKUTAN株式会社 | BAKUTAN OS | multiple_targets | 1 | 1.000000／— |
| [F238](https://prtimes.jp/main/html/rd/p/000000284.000033277.html) 各種ATSから求人情報をPORTERSに一括集約『PORTERS ATS JOB Import』を2026年10月1日にリリース | ポーターズ株式会社 | PORTERS ATS JOB Import | unknown | 1 | 1.000000／— |
| [F255](https://prtimes.jp/main/html/rd/p/000000462.000015987.html) SmartHR、AIを活用した「ブラウザ自動操作」機能を拡張。API非対応Webサービスのアカウント作成・削除を自動化 | 株式会社SmartHR | SmartHRの「ブラウザ自動操作」機能 | multiple_targets | 1 | 0.721983／— |
| [F444](https://prtimes.jp/main/html/rd/p/000000035.000145778.html) コムチュア、株式会社クボタ様の人事データ活用基盤をMicrosoft Azure上に構築 | コムチュア株式会社 | 人事データ活用基盤 | multiple_targets | 1 | 1.000000／— |
| [F512](https://prtimes.jp/main/html/rd/p/000000206.000049399.html) WHI HD、タレントマネジメント製品のAIエージェント機能を拡充 | 株式会社WHI Holdings | COMPANY Talent Management (CTM2.0) | multiple_targets | 1 | 0.951626／— |
| [F622](https://prtimes.jp/main/html/rd/p/000000030.000146610.html) 青山プランニングアーツ、企業AIを「回答するAI」から「仕事を遂行するAI」へ進化させる「AIリボーン5.5」構想を発表 | 株式会社青山プランニングアーツ | AIリボーン5.5 | unknown | 1 | 0.493034／— |
| [F673](https://prtimes.jp/main/html/rd/p/000000111.000085375.html) パソナのAI面接サービス「Career Gate」にAVITAのAPIが採用 | AVITA株式会社 | Career Gate | multiple_targets | 0 | 0.846835／— |
| [F675](https://prtimes.jp/main/html/rd/p/000000113.000019706.html) 採用AIエージェント「採用一括かんりくん」、過去の履歴や評価から返信文を自動生成する「メッセージサジェスト機能」の第一弾をリリース | HRクラウド株式会社 | 採用一括かんりくん | multiple_targets | 1 | 0.879426／— |
| [F730](https://prtimes.jp/main/html/rd/p/000000304.000139786.html) 「PeopleX AI面接」、書類選考から対人面接まで、AIネイティブ採用プラットフォームへと進化 | 株式会社PeopleX | PeopleX AI面接 | multiple_targets | 1 | 1.000000／コア |
| [F737](https://prtimes.jp/main/html/rd/p/000000376.000030113.html) カオナビ、人材データ×サーベイで現場主導の改善案を示す「カオナビエンゲージメント」をリリース | 株式会社カオナビ | multiple_targets | multiple_targets | 0 | 0.758911／— |
| [F825](https://prtimes.jp/main/html/rd/p/000000026.000045514.html) AIと目標管理を活用し、リョーサン菱洋グループの組織能力向上を支援 | クレイア・コンサルティング株式会社 | クレイアが提供する組織・人事コンサルティングサービス | multiple_targets | 1 | 0.497771／— |
| [F831](https://prtimes.jp/main/html/rd/p/000000033.000156310.html) Preferred Networksの「タレスカAI面接」が沖縄セルラー電話のインターンシップ選考において「書類では見えないポテンシャル」の可視化を確認 | 株式会社Preferred Networks | タレスカAI面接 | multiple_targets | 0 | 1.000000／— |
| [F866](https://prtimes.jp/main/html/rd/p/000000061.000078735.html) パトスロゴス、「PathosLogos Chatbot」を正式リリース | 株式会社パトスロゴス | PathosLogos Chatbot | multiple_targets | 1 | 0.777808／— |
| [F903](https://prtimes.jp/main/html/rd/p/000000113.000010333.html) 人手不足の採用現場をAIで支援。AIアバターが応募者と面接するサービスの人材会社からの問い合わせが前年同期比約2.7倍に | JetB株式会社 | Our AI面接 | multiple_targets | 1 | 0.995022／— |
| [F961](https://prtimes.jp/main/html/rd/p/000000342.000023180.html) 「AIプラストーク」 で、ヤマトコンタクトサービスの新人研修を2週間から3日へ短縮 | 株式会社プラスアルファ・コンサルティング | AIプラストーク | multiple_targets | 0 | 0.497150／— |

対象名の候補はモデル出力を保存したもの。未確定の状態を手動でreadyに変更していない。

## 件数・感度評価

全560組合せの機械条件通過は0件。以下は理由の重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| insufficient_comparison_axes | 560 |
| needs_review | 560 |
| no_meaningful_difference | 560 |
| similarity_below_threshold | 232 |
| unconfirmed_shared_purpose | 560 |

構造化・引用の修復7記事、未確認引用による除外3項目。修復不能なプロフィール0件、ペアバッチ0件。

| τ | MMR 0.65 | MMR 0.75 | MMR 0.85 |
| --- | --- | --- | --- |
| 0.50 | 保留 | 保留 | 保留 |
| 0.55 | 保留 | 保留 | 保留 |
| 0.60 | 保留 | 保留 | 保留 |
| 0.65 | 保留 | 保留 | 保留 |

採用条件は変更せず、保存判定から12設定を計算した。閾値変更による構造化の不足の解消は行わない。

## 検証・限界

- 保存本文入力ハッシュ、組織一意性、候補数、ベクトルの次元・有限値を検証。
- 全120ペアのコサイン類似度を独立再計算。最大差2.22e-16。
- 保存11項目の引用とreadyの主対象引用を原文照合。意味の正確さとは区別。
- 実データの入力順を逆にしても評価JSON全体が一致。選定ルール9件の共通検証を実施。
- 人の正解ラベルは未作成。正解率・誤採用率・誤除外率は算出していない。
- ペアの追加本文による意味の再判定は未実施。修復は構造・引用の検証失敗時に限る。未確定は保留。
- 単一モデル・固定辞書の試行。採用0組をモデル一般の性能や比較候補不在と解釈しない。

## 使用量

| 項目 | 値 |
| --- | --- |
| ローカルモデル要求 | 38 |
| 入力token | 93148 |
| 出力token | 15486 |
| 要求時間合計（秒） | 474.988 |
| 要求状態 | {"valid": 31, "validation_failed": 7} |
| OpenAI／外部／埋め込みAPI要求 | 0／0／0 |
| API料金（米ドル） | 0 |

GPU・電力等のローカル計算費用は金額換算していない。検証失敗した要求も使用量・応答履歴を残す。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c22-local-20261013/input-manifest.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c22-local-20261013/article-profiles.json)
- [selection-profiles.json](../.local/comparison-three-article-selection-c22-local-20261013/selection-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c22-local-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c22-local-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c22-local-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c22-local-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c22-local-20261013/selected-triplets.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c22-local-20261013/cluster-decisions.json)
- [evaluation.json](../.local/comparison-three-article-selection-c22-local-20261013/evaluation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c22-local-20261013/llm-usage.json)
- [source-review.json](../.local/comparison-three-article-selection-c22-local-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c22-local-20261013/real-validation.json)

[一括処理の設定・辞書](../.local/comparison-three-article-selection-c05-c30-local-20261013/cluster-config.json) / [処理スクリプト](../.local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py) / [全体報告書](comparison-three-article-selection-c05-c30-evaluation-20261013.md)

保存済み判定だけで再評価：

```powershell
python -X utf8 .local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py --clusters C22 --evaluate-only
```
