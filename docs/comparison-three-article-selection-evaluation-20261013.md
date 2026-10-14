# 3記事選定案の1クラスタ限定評価（C01）

実施日：2026-10-13（日本時間）。[提案書](comparison-three-article-selection-proposal-20261013.md)の単一クラスタ試行。

**C01の13記事・78ペア・286組合せを評価した結果、3記事の採用条件は成立せず、状態は `needs_review`。** 条件を満たす3件目を補充したり、閾値を緩めたりしていない。

## 対象・実行条件

対象は通信機器クラスタC01のみ。現在のコアはF312・F584の2件で、全所属13記事を候補とした。クラスタIDの昇順で最初のC01を、選定結果を見る前に固定した。30クラスタ中の残る29クラスタとノイズ338記事は選定・LLM送信の対象にしていない。

| 条件 | 実行内容 |
| --- | --- |
| 候補 | 13記事、13組織 |
| 入力検証 | 本文入力SHA-256一致、組織一意、候補数5以上、AI／IoT・商品サービス・タイトル除外条件を確認 |
| ベクトル | 保存済み1,536次元をL2正規化して再利用 |
| 安定度 | 6通りで基準記事と同じ非ノイズクラスタに所属した割合 |
| 初期設定 | τ=0.55、MMR重み=0.75、R重み=0.70／0.15／0.15 |
| 採用条件 | 全3ペア comparable=yes・same_target=no、共通用途、3組織・3対象、共通2項目以上、差異1項目以上 |
| LLM | `gpt-4.1-2025-04-14`、temperature=0、Structured Outputs、保存本文のみ |
| 評価方式 | 重心上位3件、メドイド＋近傍2件、最低ペア類似度最大化、提案のMMR |
| パラメータ調整 | 初期値を維持。12設定の感度確認を併記し、採用設定は変更しない |

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。入力ファイルのSHA-256、プロンプト・スキーマのハッシュは[実行マニフェスト](../.local/comparison-three-article-selection-20261013/input-manifest.json)に保存。

## 結果と基準方式との比較

| 方式（クラスタ全体から選ぶ） | 3記事 | 最低類似度 | 平均類似度 | 共通項目／差異 | 合否・理由 |
| --- | --- | ---: | ---: | ---: | --- |
| centroid_top3 | F312・F584・F965 | 0.618357 | 0.676129 | 0／0 | incompatible_article_pair、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F312・F955・F965 | 0.590536 | 0.675622 | 1／1 | unconfirmed_shared_purpose、insufficient_comparison_axes |
| maximum_minimum_similarity | F042・F289・F584 | 0.621971 | 0.653872 | 0／0 | incompatible_article_pair、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | 0／0 | no_valid_triplet |

いずれの基準方式にも同じ用途・対象・比較項目・類似度の合否条件を適用した。ベクトルの順位だけによる候補と、本文条件を満たした候補を区別している。

基準方式の共通項目数・差異数はLLM正規化による暫定値。追加照合で対応関係と表記差の誤りを確認したため、確認済みの意味的な差異としては扱わない。

## 全候補と保留・除外の内訳

プロフィール状態：`{"ready": 13}`。ペア比較可能性：`{"yes": 11, "no": 67}`。対象同一性：`{"no": 78}`。

286組合せ中の通過は0件。次の不合格理由は重複計上で、合計は組合せ数と一致しない。

| 理由 | 組合せ数 |
| --- | ---: |
| incompatible_article_pair | 281 |
| insufficient_comparison_axes | 285 |
| no_meaningful_difference | 281 |
| similarity_below_threshold | 230 |
| unconfirmed_shared_purpose | 285 |

| 比較用途グループ | 候補 |
| --- | --- |
| industrial_iot_router_gateway | F006・F042・F289 |
| satellite_iot_comm_service | F281 |
| consumer_wifi_router | F312・F965 |
| mobile_wifi_router | F584 |
| overseas_rental_wifi | F392 |
| enterprise_wifi_ap | F823 |
| industrial_wireless_module | F794 |
| business_wifi_ap | F955 |
| ha_low_ap | F690 |
| wireless_test_equipment | F689 |

## パラメータ感度（設定は変更せず）

| τ | MMR 0.65 | MMR 0.75 | MMR 0.85 |
| ---: | --- | --- | --- |
| 0.50 | 保留 | 保留 | 保留 |
| 0.55 | 保留 | 保留 | 保留 |
| 0.60 | 保留 | 保留 | 保留 |
| 0.65 | 保留 | 保留 | 保留 |

これは1クラスタ内の成立条件の感度確認であり、提案の調整用10クラスタ／評価用20クラスタの評価は実施していない。

## 構造化・正規化で検出した問題

初回の引用には改行を詰めた文字列や途中の表行・段落を飛ばした文字列があった。空白差だけはプログラムで原文の連続範囲へ復元し、その他の不一致は保存本文を使って1回再構造化した。再構造化後も原文へ復元できない項目は除外し、値を手で補っていない。

- F794：マルチバンド対応を除外。引用が原文の連続範囲として復元できないため比較項目から除外。値を推測・手修正しない。
- F823：屋外対応モデルを除外。引用が原文の連続範囲として復元できないため比較項目から除外。値を推測・手修正しない。
- F965：管理画面ログインセキュリティを除外。引用が原文の連続範囲として復元できないため比較項目から除外。値を推測・手修正しない。

初回の正規化は13記事を13グループへ分けたため、共通用途へ統一する指示を明確にして辞書を再生成した。辞書にない項目キーが返った28件は未正規化として扱い、共通項目数・差異数に使用しない。

初回の一括ペア判定には指定ペアの欠落があった。指定ペアIDをJSONオブジェクトの必須キーとして固定する形式へ変更し、全78ペアの取得を検証した。不合格の初回応答と最終応答は別ファイルに残した。

これらは試行で見つかった実装上の修正であり、選定のτ・重み・項目数条件の変更ではない。

## 追加本文照合と最終保留の理由

機械条件による代表状態は `similarity_below_threshold`。追加の本文・正規化対応の照合を別に保存し、最終状態を `needs_review` とした。次はこのチャットのアシスタントによる確認で、人の正解ラベルではない。

- F823：LLMはAP5060/AP5022/AP3020/AP3060の製品群を主対象としてreadyとした。個々のモデルのラジオ構成・利用環境を混ぜている。提案の1比較対象の特定条件を満たしたとは確認できない。
- F955：正規化でa07（メッシュネットワーク）がcloud_managementのInsight対応、a08（クラウド管理）がメッシュ対応へ入れ替わった。引用の文字一致だけではこの対応誤りを検出できない。
- F312・F955：F312のストリーム数と周波数帯が同じband_count、メッシュ・ローミング・認証がsecurity_featuresへ統合され、F955の接続台数もband_countへ入った。原子的な同一項目の正規化になっていない。
- F312・F823・F955・F965：Wi-Fi 7、Wi‑Fi 7、WiFi 7（802.11be）、Wi-Fi 7対応が異なるvalue_keyのままで、同じ規格の表記差を意味のある差異として数えている。Draftの限定も本文で確認し、宣伝表記差を差異へしない修正が必要。
- F006・F042・F289：独立用途確認では産業用IoT/M2Mの共通目的あり。最低類似度0.5225720549641047が0.55未満。現在の正規化で共通項目はcellular_standardの1項目。値を補完せず採用を保留。

全3ペアが比較可能だった5組について、さらに3記事の共通用途をLLMで確認した。産業向けF006・F042・F289は共通用途を確認。家庭ルータと法人APが混在する4組は用途・利用者の不一致となり、グループを統合しなかった。追加応答のaudience/categoryはnullで、具体的な共通用途の確認として既存辞書と併用した。

| 3記事 | 共通用途判定 | 理由 |
| --- | --- | --- |
| F006・F042・F289 | confirmed | 3ペアとも産業用IoT/M2Mゲートウェイ・ルータとして、現場設置・遠隔監視・制御・データ収集などの具体的な産業用途で一致している。利用者層やカテゴリも産業現場・IoT導入企業・現場担当者などで大きなズレはない。 |
| F312・F823・F955 | mismatch | 3ペアのshared_purposeはいずれも『Wi-Fi 7による高速無線LAN環境構築』だが、F312は家庭用、F823は大規模法人・施設、F955は中小企業向けと、用途・利用者・カテゴリが明確に異なる。単にWi-Fi 7対応という技術的共通点のみで、具体的な用途や利用者が一致しない。 |
| F312・F823・F965 | mismatch | F312とF965は家庭用高速無線LAN環境構築で一致するが、F823は法人・施設向けWi-Fi 7 APであり、主な用途・利用者が異なる。3ペアで具体的用途・利用者・カテゴリが揃わない。 |
| F312・F955・F965 | mismatch | F312とF965は家庭用高速無線LAN環境構築で一致するが、F955は中小企業向けAPであり、家庭用とは利用者・用途が異なる。3ペアで具体的用途・利用者・カテゴリが揃わない。 |
| F823・F955・F965 | mismatch | F823とF955は法人・施設向けWi-Fi 7無線LAN環境構築で近いが、F965は家庭用が主であり、3ペアで具体的用途・利用者・カテゴリが揃わない。 |

改善点はモデル別の比較対象特定、原子的な比較項目IDの固定、正規化値とraw_idの対応照合、同義表記を差異に数えない処理。この試行では判定を手で採用へ変えず、初期条件を維持して保留した。

## 検証と評価の限界

- オフラインルール検証12件通過：全3辺必須、unknown保留、組織重複、同一対象、類似度下限、項目条件不一致、差異不足、API拒否・途中終了、キャッシュ再利用など。
- 元DBは読み取り専用で使用し、保存ベクトルを再利用。公開・配信処理は呼び出していない。
- 固定した人の正解・保留ラベルがないため、構造化正解率・ペアの誤採用率／誤除外率は算出していない。
- 1クラスタだけの結果から、全クラスタへの効果やMMRの精度向上を一般化しない。
- 原文引用の文字一致は内容の意味的な正確さを保証しない。追加の本文照合結果は下記の別ファイルに保存する。
- 新しいLLM呼び出しによる判定変動は未測定。

保存された141項目の引用が原文にあること、78ペアの元空間類似度（最大差2.23e-16未満）、入力6ファイルのSHA-256不変を確認した。固定プロフィール・辞書・ペア判定を逆順にしても評価JSON全体が一致した。産業向け基準記事F042とMMRスコア0.886775354を独立再計算した。この組は採用条件未通過。

## API使用量・費用

実API要求は32回（新規埋め込み0回）。保存された30要求分の推定費用は**1.154496米ドル**。これは全要求の確定請求額ではない。

最初のF281/F312の不合格出力2件は再開時に同一監査キーを上書きしたためtoken使用量未保持。料金・token合計は保持履歴分のみ。

| 工程 | 保持要求数 | 入力token | キャッシュ入力token | 出力token | 推定米ドル |
| --- | ---: | ---: | ---: | ---: | ---: |
| normalization | 2 | 33535 | 0 | 21818 | 0.241614 |
| pair | 5 | 107959 | 0 | 4907 | 0.255174 |
| profile-repair | 3 | 9699 | 0 | 4384 | 0.054470 |
| profile | 13 | 28997 | 4608 | 14439 | 0.166594 |
| pair-v2 | 6 | 158578 | 0 | 10301 | 0.399564 |
| triad-purpose-review | 1 | 16040 | 0 | 625 | 0.037080 |

使用量は不合格応答を含む。入力2.00／キャッシュ入力0.50／出力8.00米ドル（100万tokenあたり）で算出。[OpenAI公式モデル・料金資料](https://developers.openai.com/api/docs/models/gpt-4.1)、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)を2026-10-13に確認した。

## 保存先・再評価

- [確認表HTML](../.local/comparison-three-article-selection-20261013/selection.html)
- [評価JSON](../.local/comparison-three-article-selection-20261013/evaluation.json)／[クラスタ判定](../.local/comparison-three-article-selection-20261013/cluster-decisions.json)
- [全286組合せ](../.local/comparison-three-article-selection-20261013/triplet-candidates.json)／[全78ペア](../.local/comparison-three-article-selection-20261013/pair-judgments.json)
- [記事プロフィール](../.local/comparison-three-article-selection-20261013/article-profiles.json)／[正規化辞書](../.local/comparison-three-article-selection-20261013/normalization-dictionary.json)
- [API使用量](../.local/comparison-three-article-selection-20261013/llm-usage.json)／[ルール検証](../.local/comparison-three-article-selection-20261013/rule-validation.json)
- [追加本文照合・実データ検証](../.local/comparison-three-article-selection-20261013/source-review.json)
- [実行スクリプト](../.local/comparison-three-article-selection-20261013/run-evaluation.py)

保存済みの最終判定だけで再評価するコマンド（新規API要求なし）：

```powershell
python -X utf8 .local/comparison-three-article-selection-20261013/run-evaluation.py --phase evaluate
```
