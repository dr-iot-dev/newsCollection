# 3記事選定案のC02限定評価

実施日：2026-10-13（日本時間）。[提案書](comparison-three-article-selection-proposal-20261013.md)に基づく2回目の単一クラスタ試行。

**C02の11記事・55ペア・165組合せを評価。最終状態は `needs_review`、採用は0組（0記事）。**

今回処理したのはユーザー指定のC02だけ。C01の報告書・評価データは変更していない。保存済み11所属記事全件を候補とし、ノイズと他クラスタは選定・LLM送信の対象にしていない。

## 条件と入力検証

| 項目 | 条件・結果 |
| --- | --- |
| 候補 | 11記事・11組織、現在のコアはF234・F301の2件 |
| 対象条件 | AI／IoT、公式種類「商品サービス」、タイトル除外111語、一致候補数5以上を引継ぎ |
| 入力確認 | 本文入力ハッシュ一致、組織一意性、所属C02、6通りの安定度ラベルを確認 |
| 類似度 | 保存済み1,536次元ベクトルをL2正規化して再利用 |
| 設定 | τ=0.55、MMR関連性重み0.75、R重み0.70／0.15／0.15 |
| 採用条件 | 全3ペアcomparable=yes・same_target=no、共通用途、3組織・3対象、共通2項目以上、意味のある差異1項目以上 |
| LLM | gpt-4.1-2025-04-14、temperature=0、Structured Outputs |
| 検証方式 | 重心上位3件、メドイド＋近傍2件、最低ペア類似度最大化、提案のMMR |

モデル・スコア・閾値はC01と同じ。比較項目の例と正規化のカテゴリ例はC02の製造・設備監視・工程管理に合わせた。ペアIDをスキーマの必須キーにする方式、原文引用照合、1回だけの修復、未正規化項目の除外も引き継いだ。API要求はUUIDで個別保存し、再開時に使用量を上書きしない。

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。ファイル・プロンプト・スキーマ・実装のハッシュは[実行マニフェスト](../.local/comparison-three-article-selection-c02-20261013/input-manifest.json)。

## 採用・保留の理由

機械条件の代表状態：`similarity_below_threshold`。追加本文照合：`needs_review`。

- F007・F039・F234：全3ペア比較可能・独立共通用途確認を満たす唯一の組。最低類似度0.5338902780672479（F007–F039）が初期下限0.55未満。平均0.6008031572398475。閾値を緩めず保留。

- F039：主対象はCLOUDSHIPの時系列DBと記録している一方、a06～a08にRealBoard側の稼働監視・グラフ分析・ダッシュボード機能を入れている。連携条件は元プロフィールにあるが、比較対象をDB単体かCLOUDSHIP＋RealBoard構成か確定する必要がある。

- F039・F234：F039の高速記録a01をrealtime_operation_monitoring、高速書込み・読み出しa02をdashboard_visualizationへ対応付けた。F234の実績自動収集a02も可視化へ対応付けた。記録・収集と監視・可視化を混同しており、暫定共通2項目は原文照合で確定できない。

- F007・F234：稼働監視の「対応」と具体的な機能説明の表記差が異なるvalue_keyとなり、意味のある差異に数えられている。同じ機能を異なる詳しさで記しただけかを区別する必要がある。暫定差異2項目も未確定。

- F007・F234：F007のクラウド提供a09は会社概要の一般的な事業内容を引用。F234ではサブスクリプションという課金形態をcloud_service_provisionに対応付けている。対象製品の提供方式を直接裏付ける記載とは区別が必要。

- F121・F342：対象根拠の引用が1回の修復後も原文の連続範囲として復元できずunknown。対象の名称はLLM申告を保持するが、readyの選定候補には入れない。

初期条件を満たす3記事を採用結果として出さず、選定結果JSON・CSVの採用行は空にした。

## 基準方式との比較

| 方式 | 3記事 | 最低類似度 | 平均類似度 | 共通項目／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F039・F234・F301 | 0.636769 | 0.672735 | 0／0 | incompatible_article_pair、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F039・F234・F301 | 0.636769 | 0.672735 | 0／0 | incompatible_article_pair、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F118・F301・F342 | 0.653555 | 0.672046 | 0／0 | needs_review、incompatible_article_pair、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

基準方式にも同じ本文・対象・用途・類似度の採用条件を適用。項目数・差異数は保存されたLLM正規化結果に基づき、追加照合で未確認のものは採用根拠として確定しない。

## 候補記事

| F ID／元記事 | 配信元 | 比較対象 | 帰属確率／コア | 構造化状態 | 用途グループ |
| --- | --- | --- | --- | --- | --- |
| [F007](https://prtimes.jp/main/html/rd/p/000000053.000022585.html) ソフトブレーン、esm(eセールスマネージャー)にIoTサービス「esm IoT」を追加 設備機器の稼働状況をリアルタイムで監視可能に | ソフトブレーン株式会社 | esm IoT（esm serviceの新機能） | 0.941179／— | ready | equipment_operation_monitoring、resolved_70d6eacda956 |
| [F039](https://prtimes.jp/main/html/rd/p/000000008.000084107.html) 千住スプリンクラーのDX工場プロジェクトにCLOUDSHIP®・RealBoard®が採用 | 株式会社PROMPT-X | CLOUDSHIP® | 0.969445／— | ready | manufacturing_data_platform、resolved_70d6eacda956 |
| [F118](https://prtimes.jp/main/html/rd/p/000000035.000093298.html) Smart Craft、工程管理と在庫管理を統合する新機能をリリース | 株式会社Smart Craft | Smart Craft（クラウド製造実行システム（MES）） | 1.000000／— | ready | cloud_mes_inventory |
| [F121](https://prtimes.jp/main/html/rd/p/000000043.000103807.html) 惣菜の値引き判断にAIを活用、シール発行まで業務を標準化 | 株式会社シノプス | AI値引きソリューション（sinops-CLOUD AI値引＋FLEQV® FX3-LX） | 0.980072／— | unknown | retail_discount_automation |
| [F142](https://prtimes.jp/main/html/rd/p/000000121.000086246.html) 製造・建設現場の安全DXを加速。生産性向上ツール「Patt Plus」が大幅アップデート | 国際航業株式会社 | Patt Plus | 0.913561／— | ready | onsite_safety_productivity |
| [F234](https://prtimes.jp/main/html/rd/p/000000241.000022401.html) スザキ工業所とスカイディスク、現場のDX意識から生まれた、プレス加工製造業向けリアルタイム稼働監視＆実績収集サービス「スマート・カイゼン・カウンター（SKC）」を共同リリース | 株式会社スカイディスク | Smart Kaizen Counter（SKC） | 1.000000／コア | ready | press_monitoring、resolved_70d6eacda956 |
| [F301](https://prtimes.jp/main/html/rd/p/000000033.000046119.html) 検査データを“改善に使える情報”へ － 製造現場の品質改善を支援する「Q-Smart」を正式リリース | 株式会社アダコテック | Q-Smart（キュースマート） | 1.000000／コア | ready | quality_management_platform |
| [F342](https://prtimes.jp/main/html/rd/p/000000148.000026042.html) 半年で購入数量35%減＆欠品ゼロを両立。AIエージェントが支える"ちょうどいい在庫" | 株式会社エスマット | SmartMat Cloud（スマートマットクラウド） | 1.000000／— | unknown | iot_inventory_management |
| [F556](https://prtimes.jp/main/html/rd/p/000000998.000016343.html) 北欧100年のスマート農機メーカー Sveaverken（スベアワーケン）社の「Sveaverken F200自動操舵システム」販売スタート | 株式会社セキド | Sveaverken F200自動操舵システム | 0.991574／— | ready | agricultural_autosteering |
| [F638](https://prtimes.jp/main/html/rd/p/000000053.000124870.html) サブスクリプション『図面管理ソリューション PRIMO-X』を開発 | 株式会社ＹＵＡＳＡ | 図面管理ソリューション PRIMO-X | 1.000000／— | ready | drawing_management |
| [F808](https://prtimes.jp/main/html/rd/p/000000015.000084801.html) スウェーデンのコンソーシアムがSilex MicrosystemsABの株式買収を完了 | 株式会社協同インターナショナル | MEMS専業ファウンドリーサービス（Silex MicrosystemsAB） | 0.887215／— | ready | mems_foundry_service |

## ペア・組合せの集計

プロフィール状態：`{"ready": 9, "unknown": 2}`。比較可能性：`{"yes": 9, "no": 46}`。同一対象：`{"no": 55}`。

全165組合せ中、機械条件通過は0件。不合格理由は重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| incompatible_article_pair | 164 |
| insufficient_comparison_axes | 164 |
| needs_review | 81 |
| no_meaningful_difference | 164 |
| similarity_below_threshold | 126 |
| unconfirmed_shared_purpose | 164 |

## 全3ペアを満たす組合せの共通用途確認

| 3記事 | 状態 | 共通目的・理由 |
| --- | --- | --- |
| F007・F039・F234 | confirmed | 製造現場の設備稼働監視・実績収集・データ可視化／3記事とも主な用途は『製造現場の設備稼働状況をリアルタイムで監視し、実績データを自動収集・可視化すること』で一致している。対象ユーザーも製造業の現場担当者や設備管理者で共通し、カテゴリも『設備稼働監視・実績収集IoTシステム』として正規化できる。各記事の記載から、用途・利用者・カテゴリの共通性が十分に根拠付けられるため。 |

## パラメータ感度

初期設定を採用したまま、τ=0.50／0.55／0.60／0.65とMMR重み=0.65／0.75／0.85の12設定を保存判定で確認した。調整用10クラスタ／評価用20クラスタの評価ではない。

| τ | MMR 0.65 | MMR 0.75 | MMR 0.85 |
| --- | --- | --- | --- |
| 0.50 | F007・F039・F234（本文照合未通過） | F007・F039・F234（本文照合未通過） | F007・F039・F234（本文照合未通過） |
| 0.55 | 保留 | 保留 | 保留 |
| 0.60 | 保留 | 保留 | 保留 |
| 0.65 | 保留 | 保留 | 保留 |

τ=0.50の組合せは保存済みLLM値による機械候補であり、原文照合を通過した採用結果ではない。初期τ=0.55を維持している。基準記事F234と初期MMRスコア0.889366624を独立再計算したが、この組は初期採用条件未通過。

初回の正規化応答にはF007だけが含まれ、他10記事が欠落していた。全F ID・raw_idをスキーマの必須キーにする形式で再実行し、11記事の正規化記録を取得した。構造化の不合格出力と最終応答を履歴に残し、token使用量に含めている。

## 検証・限界

- オフラインルール検証12件通過。実データの入力順を逆にしても評価JSONが一致。
- 保存された98項目の引用が原文に存在することを確認。意味の正しさの保証とは分けて扱う。
- 全55ペアの類似度を独立再計算（最大差2.22e-16）。入力ファイルとC01の保存成果物の不変を確認。
- 修復後も原文引用を復元できず除外した項目は1件。辞書に対応しないため共通項目として使わない項目は0件。
- 人の固定正解ラベルは未作成。構造化やペア判定の正解率・誤採用率・誤除外率は算出していない。
- 1クラスタだけの評価であり、全クラスタへの一般化やMMRの優位性を示すものではない。
- 新規LLM呼び出しによる判定変動は未測定。

## API使用量と推定費用

API要求22回、保持履歴22件、usage未取得0件。追加埋め込みAPIは0回。推定費用は**0.613354米ドル**（確定請求額ではない）。

| 工程 | 要求 | 入力token | キャッシュ入力token | 出力token | 推定米ドル |
| --- | --- | --- | --- | --- | --- |
| triad-purpose-review | 1 | 5508 | 0 | 225 | 0.012816 |
| profile | 11 | 25726 | 0 | 13052 | 0.155868 |
| pair-v2 | 5 | 86184 | 0 | 7107 | 0.229224 |
| normalization | 1 | 14737 | 0 | 2351 | 0.048282 |
| profile-repair | 3 | 10832 | 0 | 4400 | 0.056864 |
| normalization-v2 | 1 | 20482 | 0 | 8667 | 0.110300 |

入力2.00／キャッシュ入力0.50／出力8.00米ドル（100万tokenあたり）。[OpenAI公式モデル・料金資料](https://developers.openai.com/api/docs/models/gpt-4.1)を前回同日に確認した料金を使用。API拒否・途中終了と正常なunknown判定は分けて記録している。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c02-20261013/input-manifest.json)
- [evaluation.json](../.local/comparison-three-article-selection-c02-20261013/evaluation.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c02-20261013/cluster-decisions.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c02-20261013/article-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c02-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c02-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c02-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c02-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c02-20261013/selected-triplets.json)
- [purpose-resolutions.json](../.local/comparison-three-article-selection-c02-20261013/purpose-resolutions.json)
- [purpose-regrouping.json](../.local/comparison-three-article-selection-c02-20261013/purpose-regrouping.json)
- [source-review.json](../.local/comparison-three-article-selection-c02-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c02-20261013/real-validation.json)
- [rule-validation.json](../.local/comparison-three-article-selection-c02-20261013/rule-validation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c02-20261013/llm-usage.json)
- [selection.html](../.local/comparison-three-article-selection-c02-20261013/selection.html)
- [run-evaluation.py](../.local/comparison-three-article-selection-c02-20261013/run-evaluation.py)

保存済みの判定だけで再評価（新規API要求なし）：

```powershell
python -X utf8 .local/comparison-three-article-selection-c02-20261013/run-evaluation.py --phase evaluate
```
