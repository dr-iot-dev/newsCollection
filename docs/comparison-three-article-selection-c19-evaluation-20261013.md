# 3記事選定案のC19限定・ローカル評価

入力データ日：2026-10-13。評価完了日時：2026-10-13T23:16:44.320807+09:00。 [提案書](comparison-three-article-selection-proposal-20261013.md)に基づく評価。

**C19のみの26記事・325ペア・2600組合せを処理した。状態 `needs_review`、採用0組。OpenAI API・外部API・新規埋め込みAPIは0回。**

全所属記事を候補にし、現在のコアは1件。別クラスタ・ノイズは今回のモデル入力に含めない。C01〜C04の結果は別の保存先で保持し、一括処理終了時にSHA-256で不変を照合する。

## 実行方式

| 項目 | 内容 |
| --- | --- |
| モデル | DeepSeek-R1-14B-Q4_K:latest（Ollama 0.5.7、実体Q6_K・14.8B） |
| 固定ダイジェスト | 2c8fc88a397e2753c57dc5fadf895fa7723d8cf5958f4c3bde34b7681c79b924 |
| 接続先 | http://127.0.0.1:11434 のみ |
| 推論設定 | temperature=0、seed=42、num_ctx=8192、ネイティブraw入力 |
| 構造化 | 保存タイトル・本文全文。引用照合、失敗時は修復1回、修復不能はprocessing_failedを記録しunknownへ |
| 正規化 | 固定用途11分類・項目15種類。タイトル一覧から事前定義し、本文から支持できる用途だけ分類 |
| ペア判定 | 全ペアを最大8ペアずつ推論。主対象未確定は採用判定unknown。元判定は別フィールドに保持 |
| 初期条件 | τ=0.55、MMR重み0.75、R重み0.70／0.15／0.15、3ペア全通過・3組織／3対象・共通2項目以上・差異1項目以上 |

C03・C04と同じモデル・入力形式・採用条件を使った。用途辞書・比較項目は分野ごとに固定した。提案のLLM自由生成による正規化辞書を固定辞書へ変更しているため、分類辞書の不足による見落としは未評価。C01・C02とはモデル・辞書方式が異なる。

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。モデル要求ごとのプロンプト・スキーマと応答、版・ハッシュを保存した。

## 結果と保留理由

機械条件：`insufficient_comparable_articles`。追加品質確認：`needs_review`。

プロフィール：`{"multiple_targets": 25, "unknown": 1}`。採用用comparable：`{"unknown": 325}`。

採用制御前comparable：`{"unknown": 236, "no": 42, "yes": 47}`。主対象未確定に対する制御は325ペア。

- F122・F147・F367・F412・F469・F593・F595・F623・F641・F708・F722・F748・F759・F763・F782・F807・F814・F835・F896・F916・F951・F952・F957・F966・F969・F973：readyは0件、2項目未満の抽出は24件。未確定の対象や不足項目を類似度・MMRだけで補完しない。

- F122・F147・F367・F412・F469・F593・F595・F623・F641・F708・F722・F748・F759・F763・F782・F807・F814・F835・F896・F916・F951・F952・F957・F966・F969・F973：採用可能な主対象引用と保存比較項目の引用が本文に含まれることを確認。文字列一致は意味・分類の正しさの保証ではない。

- F122・F147・F367・F412・F469・F593・F595・F623・F641・F708・F722・F748・F759・F763・F782・F807・F814・F835・F896・F916・F951・F952・F957・F969・F973：multiple_targetsで対象候補を示す一方、other_targetsが空。主対象を絞れない理由・残り対象が十分に記録されていない。モデルの状態を手動でreadyに変えない。

採用0組は、このローカルモデル・固定辞書・初期条件で採用を確定できなかったという結果。比較可能な3記事が存在しないことの証明ではない。

## 基準方式との比較

| 方式 | 記事 | 最低類似度 | 平均類似度 | 共通／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F782・F916・F973 | 0.551219 | 0.602916 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F814・F916・F951 | 0.648519 | 0.664333 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F708・F722・F835 | 0.649889 | 0.741620 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

高い類似度だけで対象・用途・比較項目の不明を通過させない。MMRによる順位付けは機械条件を通過した候補に限定する。

## 候補記事

| 記事 | 組織 | モデルの対象候補 | 状態 | 項目数 | 帰属確率／コア |
| --- | --- | --- | --- | --- | --- |
| [F122](https://prtimes.jp/main/html/rd/p/000000047.000065365.html) 生成AI対応「早大 スマートエスイーDXコース(第4期) 」10月開講 | 学校法人早稲田大学 | スマートエスイーDXコース | multiple_targets | 1 | 0.573968／— |
| [F147](https://prtimes.jp/main/html/rd/p/000000166.000155740.html) 「AIエージェント・ストラテジスト資格」回答者の74.4％が「実務に活かせる」と回答 | 一般社団法人AICX協会 | AICX協会の「AIエージェント・ストラテジスト資格」 | multiple_targets | 1 | 0.470259／— |
| [F367](https://prtimes.jp/main/html/rd/p/000000273.000006034.html) 「やりたいこと、ありますか？」長崎大学の学生31名が、生成AIで”5年後の自分”を漫画に | 木村情報技術株式会社 | MOOTOON STUDIO | multiple_targets | 1 | 0.569295／— |
| [F412](https://prtimes.jp/main/html/rd/p/000000008.000155127.html) 仕事の現場を再現した対話型シミュレーション機能を追加！主体的に考え、行動する力を育てる企業向け学習サービス『FRACTAL』 | FutureRays株式会社 | FRACTAL（フラクタル） | multiple_targets | 1 | 0.448850／— |
| [F469](https://prtimes.jp/main/html/rd/p/000000060.000078998.html) 『ITパスポート』の資格勉強をカードゲームで。中高生の「情報Ⅰ」学習を支える『デジ連』と共同開発した“情報カードゲーム”が2作同時発売。 | 株式会社TRYBE | ITパスポートかるた（テクノロジ編）/ITパスポートかるた（ビジネス、セキュリティ・倫理編） | multiple_targets | 1 | 0.451766／— |
| [F593](https://prtimes.jp/main/html/rd/p/000000007.000156343.html) 「万能な予測モデルは存在しない」― 古典統計から時系列基盤モデルまでを一冊で俯瞰する実務書『AI時代の時系列予測』を刊行 | 株式会社MOAI Lab | professional_book | multiple_targets | 0 | 0.380905／— |
| [F595](https://prtimes.jp/main/html/rd/p/000000009.000016003.html) 【ITCOLLEGE】ゼロからAI時代の設計・マネジメントを学び、現場叩き上げの上流エンジニアへ。経験2～4年目エンジニア向け「次世代リーダー・マネージャー養成研修」を2026年11月より毎月開講 | 株式会社リゾーム | ITCOLLEGE | multiple_targets | 6 | 0.567962／— |
| [F623](https://prtimes.jp/main/html/rd/p/000000031.000018563.html) Nature Service、森を活かして事業に変える「森林活用企画士」制度を創設。第1期生開講へ | 特定非営利活動法人 Nature Service | forest_training | multiple_targets | 4 | 0.836809／— |
| [F641](https://prtimes.jp/main/html/rd/p/000000055.000127223.html) 大阪電気通信大学発ベンチャーが開発した移動ロボット教材「EduCar-spicon」を奈良県立王寺工業高校へ30台納入～「1人1台」で組み立てからAIまで段階的に学べる先進的STEAM教育を支援～ | 学校法人大阪電気通信大学 | EduCar-spicon | multiple_targets | 1 | 0.569433／— |
| [F708](https://prtimes.jp/main/html/rd/p/000000195.000089608.html) 管理職研修を"やりっぱなし"にしない。HQとNEWONE、プロコーチ×AIで行動変容を可視化する研修伴走サービスを共同開発 | 株式会社HQ | One Cue | multiple_targets | 1 | 0.902810／— |
| [F722](https://prtimes.jp/main/html/rd/p/000000245.000038467.html) NEWONE、研修後3ヶ月の「行動変容」までコミットする『【One Cue（ワン・キュー）】』をリリース | 株式会社NEWONE | One Cue | multiple_targets | 1 | 1.000000／— |
| [F748](https://prtimes.jp/main/html/rd/p/000000719.000006978.html) Zenken、「エンゲージメンター」を組織開発・管理職育成領域へ拡充 | Zenken株式会社 | エンゲージメント支援サービス「エンゲージメンター" | multiple_targets | 1 | 1.000000／— |
| [F759](https://prtimes.jp/main/html/rd/p/000001233.000048998.html) 今年こそ学びを習慣化！ベネッセとコクヨが数万件のデータから導いた大人の学びの「継続の秘訣」を発表 | コクヨ株式会社 | 大人のやる気ペン | multiple_targets | 1 | 0.453993／— |
| [F763](https://prtimes.jp/main/html/rd/p/000001432.000000120.html) 今年こそ学びを習慣化！ベネッセとコクヨが数万件のデータから導いた大人の学びの「継続の秘訣」を発表 | 株式会社ベネッセコーポレーション | Udemy Business | multiple_targets | 1 | 0.551259／— |
| [F782](https://prtimes.jp/main/html/rd/p/000000002.000191615.html) 株式会社YOAKE、ゼロ高等学院の新体制を発表生まれによらず経済的に自立し、進学・就職・起業を自ら選べる高校教育へ | 株式会社YOAKE | zero_higher_college | multiple_targets | 1 | 1.000000／コア |
| [F807](https://prtimes.jp/main/html/rd/p/000000014.000073572.html) 株式会社コトの発音評定AI「SeePhony®」が英語塾 J PREPの新アプリ「J PREP Dojo」に採用 | 株式会社コト | SeePhony® | multiple_targets | 1 | 0.444533／— |
| [F814](https://prtimes.jp/main/html/rd/p/000000019.000147692.html) 評価から継続的な改善まで学ぶ実践書『LLMアプリケーション評価駆動開発』が9月24日に翔泳社から発売 | 株式会社ジェネラティブエージェンツ | 『LLMアプリケーション評価駆動開発 継続的に改善し運用していくための実践知』 | multiple_targets | 1 | 0.459188／— |
| [F835](https://prtimes.jp/main/html/rd/p/000000035.000157749.html) U-ZERO、フィードバックカルチャー研修を拡充アサーティブや1on1、コーチャビリティ研修など 8プログラムを新設 | 株式会社U-ZERO | U-ZERO フィードバックカルチャー研修 | multiple_targets | 1 | 1.000000／— |
| [F896](https://prtimes.jp/main/html/rd/p/000000098.000037448.html) 大阪電気通信大学「物理学1・演習」でAI講師を活用、一人ひとり異なる問題で自ら解く学びを支援 | 株式会社DOU | OECU AI講師 | multiple_targets | 1 | 0.573968／— |
| [F916](https://prtimes.jp/main/html/rd/p/000000129.000028252.html) シナモンAI、三菱商事へ「AIトランスフォーメーション・企業風土変革研修」を提供 | 株式会社シナモン | AIトランスフォーメーション・企業風土変革研修 | multiple_targets | 1 | 0.569669／— |
| [F951](https://prtimes.jp/main/html/rd/p/000000259.000086740.html) AI時代の新しい教え方・学び方を提供する研修ソリューション「UMU AGL」をローンチ | ユームテクノロジージャパン株式会社 | UMU AGL | multiple_targets | 1 | 0.569669／— |
| [F952](https://prtimes.jp/main/html/rd/p/000000267.000024975.html) ロイロノート、次期学習指導要領に向けたAI機能の開発方針を発表 | 株式会社LoiLo | LoiNote School | multiple_targets | 1 | 0.573968／— |
| [F957](https://prtimes.jp/main/html/rd/p/000000296.000062811.html) 株式会社イーオンホールディングス、2026年10月6日（火）に「atama＋塾 緑井校」をオープン！ | 株式会社イーオン | atama＋塾 | multiple_targets | 1 | 0.573968／— |
| [F966](https://prtimes.jp/main/html/rd/p/000000377.000006391.html) スクー、鹿児島県日置市にて「つながる学び合いカレッジ powered by Schoo Mesh」第2期を開講 | 株式会社Schoo | Schoo Mesh | unknown | 1 | 1.000000／— |
| [F969](https://prtimes.jp/main/html/rd/p/000000408.000055026.html) 「旺文社 受験生のための英検®カコモン」、2025年度第2回の過去問を新規搭載！ ライティングAI採点対応によりスコアアップを可能に！ | 株式会社旺文社 | 受験生のための英検®カコモン | multiple_targets | 1 | 0.474369／— |
| [F973](https://prtimes.jp/main/html/rd/p/000000493.000030192.html) エクサウィザーズ、イオンの次世代経営幹部候補の可視化・育成を支援 | 株式会社エクサウィザーズ | ExaBase RolePlay | multiple_targets | 1 | 0.442324／— |

対象名の候補はモデル出力を保存したもの。未確定の状態を手動でreadyに変更していない。

## 件数・感度評価

全2600組合せの機械条件通過は0件。以下は理由の重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| insufficient_comparison_axes | 2600 |
| needs_review | 2600 |
| no_meaningful_difference | 2598 |
| similarity_below_threshold | 2359 |
| unconfirmed_shared_purpose | 2600 |

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
- 全325ペアのコサイン類似度を独立再計算。最大差4.44e-16。
- 保存33項目の引用とreadyの主対象引用を原文照合。意味の正確さとは区別。
- 実データの入力順を逆にしても評価JSON全体が一致。選定ルール9件の共通検証を実施。
- 人の正解ラベルは未作成。正解率・誤採用率・誤除外率は算出していない。
- ペアの追加本文による意味の再判定は未実施。修復は構造・引用の検証失敗時に限る。未確定は保留。
- 単一モデル・固定辞書の試行。採用0組をモデル一般の性能や比較候補不在と解釈しない。

## 使用量

| 項目 | 値 |
| --- | --- |
| ローカルモデル要求 | 74 |
| 入力token | 219864 |
| 出力token | 35135 |
| 要求時間合計（秒） | 1087.251 |
| 要求状態 | {"valid": 67, "validation_failed": 7} |
| OpenAI／外部／埋め込みAPI要求 | 0／0／0 |
| API料金（米ドル） | 0 |

GPU・電力等のローカル計算費用は金額換算していない。検証失敗した要求も使用量・応答履歴を残す。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c19-local-20261013/input-manifest.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c19-local-20261013/article-profiles.json)
- [selection-profiles.json](../.local/comparison-three-article-selection-c19-local-20261013/selection-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c19-local-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c19-local-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c19-local-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c19-local-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c19-local-20261013/selected-triplets.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c19-local-20261013/cluster-decisions.json)
- [evaluation.json](../.local/comparison-three-article-selection-c19-local-20261013/evaluation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c19-local-20261013/llm-usage.json)
- [source-review.json](../.local/comparison-three-article-selection-c19-local-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c19-local-20261013/real-validation.json)

[一括処理の設定・辞書](../.local/comparison-three-article-selection-c05-c30-local-20261013/cluster-config.json) / [処理スクリプト](../.local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py) / [全体報告書](comparison-three-article-selection-c05-c30-evaluation-20261013.md)

保存済み判定だけで再評価：

```powershell
python -X utf8 .local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py --clusters C19 --evaluate-only
```
