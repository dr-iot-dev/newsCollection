# 3記事選定案のC04限定・ローカル評価

実施日：2026-10-13（日本時間）。[提案書](comparison-three-article-selection-proposal-20261013.md)に基づく単一クラスタ評価。

**C04の19記事・171ペア・969組合せをローカル処理した。OpenAI API・外部API・埋め込みAPIはいずれも0回。最終状態は `needs_review`、採用は0組。**

C01〜C03の結果とは別の保存先で実行し、前の成果物の不変を照合した。C04の全所属19記事を候補にした。現在のコアは0件。ノイズと他クラスタは選定・モデル入力の対象にしていない。

## 実行方式と提案からの変更

| 項目 | 実行内容 |
| --- | --- |
| ローカル推論 | Ollama 0.5.7、DeepSeek-R1-14B-Q4_K:latest |
| 固定モデル | 2c8fc88a397e2753c57dc5fadf895fa7723d8cf5958f4c3bde34b7681c79b924 |
| 量子化 | モデル名にQ4_Kとあるが、OllamaメタデータではQ6_K（14.8B）。名称と実体を区別して記録 |
| 接続先 | http://127.0.0.1:11434 のみ。外部URLへのモデル要求・APIキーの読込みなし |
| 推論設定 | temperature=0、seed=42、num_ctx=8192。既存モデルの設定ファイルは変更しない |
| 構造化 | 保存本文全文をローカルモデルへ入力。原文引用を機械照合。失敗は1回だけ修復し、未確認の値は除外・保留 |
| 正規化 | C04向け固定用途辞書・原子的な比較項目ID。モデルの自由生成辞書とは区別 |
| ペア判定 | 全171ペアを8ペアずつローカルモデルで判定。入力プロフィールの主対象が未確定なら採用用comparableはunknown |
| 数値計算 | 元の1,536次元保存ベクトル・6条件の安定度を再利用。MMRと全組合せはPythonで計算 |
| 初期設定 | τ=0.55、MMR関連性重み0.75、R重み0.70／0.15／0.15、共通2項目以上・差異1項目以上 |

C03と同じモデルダイジェスト・推論設定・採用条件を使用した。用途辞書13分類・比較項目14種類と用途を区別するプロンプト例は、C04のセキュリティ・開発分野に合わせて固定した。C03の対象本文や判定キャッシュは今回の推論へ流用していない。

LLM工程のプロバイダーをOpenAIからローカルOllamaに変更し、正規化は固定辞書を使った。数値条件・全3ペア必須・3組織／3対象の条件は引き継いだ。モデル、入力テンプレート、辞書方式がC01・C02と異なるため、各結果を同じモデルの精度比較としては扱わない。

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。ハッシュ・プロンプト版・モデルダイジェスト・実装版は[input-manifest.json](../.local/comparison-three-article-selection-c04-local-20261013/input-manifest.json)。

## 結果・保留理由

機械条件の代表状態：`insufficient_comparable_articles`。追加の原文・処理品質確認：`needs_review`。

- F017・F024・F054・F068・F078・F112・F123・F129・F130・F134・F135・F140・F189・F196・F241・F303・F346・F667・F910：今回のローカルモデルのプロフィールにreadyは1件。比較対象・用途・項目が未確定の入力を類似度やMMRで自動採用しない。この結果だけでC04に比較可能な記事が存在しないとは判断できない。

- F017・F024・F054・F068・F078・F112・F123・F129・F130・F134・F135・F140・F189・F196・F241・F303・F346・F667・F910：モデル要求の接続先は127.0.0.1:11434のみ。OpenAI API・外部エンドポイント・APIキー読込み・追加埋め込みは使用していない。

- F017・F024・F068・F078・F112・F123・F129・F134・F135・F140・F189・F196・F241・F346・F667・F910：対象候補を記載しother_targetsが空である一方、状態をmultiple_targetsとする出力がある。主対象を絞れない理由や残りの対象が十分に示されていないため、対象名の候補と確定した比較対象は分け、原文確認が必要。

- F017・F024・F054・F068・F078・F112・F123・F129・F130・F134・F135・F140・F189・F196・F241・F303・F346・F667・F910：2項目未満の抽出があり、本文にないという判定とローカルモデルが抽出できなかった可能性を区別できない。条件を緩めて不足項目を補っていない。

- F054・F078・F241：保存原文との抜き取り照合では、F054のavailabilityが提供条件ではなく参考訳の発表日を引用し、F078は観測データ連携を主目的とする本文に対してai_agent_governanceのみを出力し、F241のdeploymentは導入環境ではなくスキーマ理解を値にしている。引用の文字列一致だけでは用途分類・項目割当ての正しさを保証しない。モデル出力の手動書換えや不足値の補完は行っていない。

**採用0組は、このローカル推論・辞書・初期条件で採用を確定できなかったという結果。C04に比較可能な3記事が存在しないことの証明ではない。**

## 基準方式との比較

| 方式 | 3記事 | 最低類似度 | 平均類似度 | 共通／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F017・F068・F189 | 0.659124 | 0.680126 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F068・F135・F189 | 0.668323 | 0.683229 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F068・F135・F241 | 0.686690 | 0.692422 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

基準方式にも同じ本文・用途・対象・比較項目の条件を適用した。高い類似度だけでは対象不明・比較用途不明の判定を通過させない。

## 候補記事と構造化状態

| 記事 | 組織 | ローカルモデルの対象候補 | 状態 | 項目数 | 帰属確率／コア |
| --- | --- | --- | --- | --- | --- |
| [F017](https://prtimes.jp/main/html/rd/p/000000215.000029239.html) ServiceNow、業界で最も包括的なセキュリティソリューションであるAutonomous Securityを発表 | ServiceNow Japan合同会社 | ServiceNow Autonomous Security | multiple_targets | 1 | 0.818369／— |
| [F024](https://prtimes.jp/main/html/rd/p/000000011.000147023.html) MathWorks、MATLAB および Simulink の Release 2026b を発表 | マスワークス合同会社 | Simulink Variant Manager, Visual Inspection Toolbox, Polyspace Test Server | multiple_targets | 0 | 0.632109／— |
| [F054](https://prtimes.jp/main/html/rd/p/000000004.000147512.html) Rapid7、脅威データを攻撃者への対抗力に変える 「Rapid7 Intelligence」を発表 | Ｒａｐｉｄ７　Ｊａｐａｎ株式会社 | Rapid7 Intelligence | ready | 1 | 0.856400／— |
| [F068](https://prtimes.jp/main/html/rd/p/000000053.000075720.html) 複数のAIプラットフォームを横断し、エージェントのリスクを可視化・制御する「Citadel Radar for Agents」を発表 | 株式会社Citadel AI | Citadel Radar for Agents | multiple_targets | 1 | 0.662481／— |
| [F078](https://prtimes.jp/main/html/rd/p/000000105.000077474.html) Datadog、AIエージェントに統合オブザーバビリティデータへの安全かつリアルタイムなアクセスを提供する「MCP Server」を発表 | Datadog Japan合同会社 | Datadog MCP Server | multiple_targets | 1 | 0.750106／— |
| [F112](https://prtimes.jp/main/html/rd/p/000000018.000168998.html) Varonis、かつてないデータ増加時代に対応する「データ ライフサイクル マネジメント(DLM)」を発表 | Varonis Systems Japan株式会社 | Varonis DLM | multiple_targets | 0 | 0.979851／— |
| [F123](https://prtimes.jp/main/html/rd/p/000000052.000107680.html) クラロティ、新機能「Visibility Orchestration（可視性オーケストレーション）」で資産の可視化と実用的なリスク削減策を最適化 | Claroty Ltd. | ClarotyxDome | multiple_targets | 1 | 0.870516／— |
| [F129](https://prtimes.jp/main/html/rd/p/000000071.000056974.html) GitLabがGitLab 19.4をリリース | GitLab Inc. | GitLab Duo Agent Platform | multiple_targets | 1 | 0.739010／— |
| [F130](https://prtimes.jp/main/html/rd/p/000000072.000118698.html) AIを活用した要求ベースのテスト作成機能を搭載：ベクターの「VectorCAST 2026」 | ベクター・ジャパン株式会社 | VectorCAST 2026 | unknown | 1 | 0.638293／— |
| [F134](https://prtimes.jp/main/html/rd/p/000000084.000073972.html) プルーフポイント、AI時代に従来の防御が見逃す攻撃を阻止 | 日本プルーフポイント株式会社 | Proofpoint Agentic Collaboration Security system | multiple_targets | 0 | 1.000000／— |
| [F135](https://prtimes.jp/main/html/rd/p/000000087.000072250.html) Cohesity、AIエージェントを支えるインフラストラクチャを保護・復旧する「Cohesity Agent Resilience」を発表 | Cohesity Japan株式会社 | Cohesity Agent Resilience | multiple_targets | 0 | 0.750106／— |
| [F140](https://prtimes.jp/main/html/rd/p/000000118.000055108.html) ゼットスケーラー、AI主導の脅威を封じ込める「Zscaler Agentic SOC」を発表 | ゼットスケーラー株式会社 | Zscaler Agentic SOC | multiple_targets | 1 | 1.000000／— |
| [F189](https://prtimes.jp/main/html/rd/p/000000019.000156001.html) AIセキュリティのCoWorker、国内初の自律型動的マルウェア解析AIプラットフォーム「Blue Agent for マルウェア解析」を発表。AIが解析を進め、人は判断に集中 | CoWorker株式会社 | Blue Agent for マルウェア解析 | multiple_targets | 0 | 0.636181／— |
| [F196](https://prtimes.jp/main/html/rd/p/000000027.000089968.html) レジデンシャルプロキシ候補を評価・可視化する脅威インテリジェンス機能を「Senda Nexus」に追加 | 株式会社レインフォレスト | Residential Proxy Intelligence | multiple_targets | 1 | 1.000000／— |
| [F241](https://prtimes.jp/main/html/rd/p/000000314.000017545.html) CData、AIと業務システムをつなぐ単一の統制基盤『Connect AI Gateway』をリリース | CData Software Japan 合同会社 | CData Connect AI Gateway | multiple_targets | 1 | 0.750106／— |
| [F303](https://prtimes.jp/main/html/rd/p/000000045.000108014.html) Vectra AI、攻撃者のAIを悪用した活動に対し、瞬時に検知・防御する次世代プラットフォームを発表 | Vectra AI Japan株式会社 | Vectra AIの次世代プラットフォーム | unknown | 0 | 1.000000／— |
| [F346](https://prtimes.jp/main/html/rd/p/000000177.000031049.html) クラウドストライク、エンドポイントにおける優位性をソフトウェアサプライチェーン保護へ拡張 | クラウドストライク合同会社 | Real-Time Supply Chain Attack Protection | multiple_targets | 1 | 1.000000／— |
| [F667](https://prtimes.jp/main/html/rd/p/000000101.000138449.html) OrcaRouter、サイバーセキュリティ研究向けモデル「OrcaSAQ-2 Cyber 27B Uncensored」のGGUF | FlashLabs株式会社 | OrcaSAQ-2 Cyber 27B Uncensored | multiple_targets | 1 | 0.662481／— |
| [F910](https://prtimes.jp/main/html/rd/p/000000121.000061678.html) Cloudflare、「検索か、AI学習か」の二者択一を解消 | クラウドフレアジャパン株式会社 | Cloudflareのクローラー制御機能 | multiple_targets | 1 | 0.750106／— |

対象名の候補はローカルモデルの申告を保存したもの。状態がreadyでなければ確定した比較対象として使用していない。

## 件数と失敗段階

プロフィール状態：`{"multiple_targets": 16, "ready": 1, "unknown": 2}`。採用に使うペア比較可能性：`{"unknown": 171}`。

全969組合せ中、通過0件。次の理由は重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| insufficient_comparison_axes | 969 |
| needs_review | 969 |
| no_meaningful_difference | 969 |
| similarity_below_threshold | 677 |
| unconfirmed_shared_purpose | 969 |

モデルの元のcomparable判定：`{"unknown": 144, "yes": 18, "no": 9}`。主対象が未確定のプロフィールを含む171ペアにはunknownへの採用制御を適用し、元判定はoriginal_comparable・original_same_targetとして保持した。

引用修復は9記事で実施。修復後も原文との一致を確認できなかった11項目はrejected_axesに理由を残して除外した。

今回の保留は、3記事の比較可否を確定する前段の構造化で必要情報が揃わなかったことによる。MMRの順位やτの調整で解消できる種類の不足とは扱わない。

## パラメータ感度

閾値・重みは変更せず、保存判定を使って12設定を計算した。プロフィール等の保留を閾値の変更で解消したとは扱わない。

| τ | MMR 0.65 | MMR 0.75 | MMR 0.85 |
| --- | --- | --- | --- |
| 0.50 | 保留 | 保留 | 保留 |
| 0.55 | 保留 | 保留 | 保留 |
| 0.60 | 保留 | 保留 | 保留 |
| 0.65 | 保留 | 保留 | 保留 |

## 検証と限界

- ローカル選定のルール検証9件通過。実データの入力順を逆にしても最終評価JSON全体が一致。
- 全171ペアのコサイン類似度を独立再計算（最大差2.22e-16）。保存本文入力ハッシュ、組織一意性、元入力ファイル不変を確認。
- 保存された13項目の引用が原文にあることを確認。意味の正確さとは区別。
- C01〜C03の既存1042ファイルのSHA-256不変を確認。
- 正解・保留の人による固定ラベルは未作成。誤採用率・誤除外率・正解率は算出していない。
- 単一クラスタ・単一ローカルモデルの試行。ローカルモデル一般の精度、他クラスタでの成立率、MMRの優位性は未評価。

## ローカル処理の使用量

| 項目 | 結果 |
| --- | --- |
| 工程内のローカルモデル要求 | 50 |
| 診断を含むローカル推論要求 | 50 |
| 工程内入力token | 153894 |
| 工程内出力token | 21906 |
| 工程内要求時間合計（秒） | 671.546 |
| OpenAI API要求 | 0 |
| 外部API要求 | 0 |
| 新規埋め込み要求 | 0 |
| API料金（米ドル） | 0 |

ローカルのGPU・電力等の計算費用は金額換算していない。プロトコル上の成功と記事内容の正しい判定は分ける。C03で確認済みのネイティブ入力形式を初回から使用し、各要求・応答・修復履歴を保存した。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c04-local-20261013/input-manifest.json)
- [local-runtime.json](../.local/comparison-three-article-selection-c04-local-20261013/local-runtime.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c04-local-20261013/article-profiles.json)
- [selection-profiles.json](../.local/comparison-three-article-selection-c04-local-20261013/selection-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c04-local-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c04-local-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c04-local-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c04-local-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c04-local-20261013/selected-triplets.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c04-local-20261013/cluster-decisions.json)
- [evaluation.json](../.local/comparison-three-article-selection-c04-local-20261013/evaluation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c04-local-20261013/llm-usage.json)
- [source-review.json](../.local/comparison-three-article-selection-c04-local-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c04-local-20261013/real-validation.json)
- [rule-validation.json](../.local/comparison-three-article-selection-c04-local-20261013/rule-validation.json)
- [selection.html](../.local/comparison-three-article-selection-c04-local-20261013/selection.html)
- [run-local.py](../.local/comparison-three-article-selection-c04-local-20261013/run-local.py)
- [selection-core.py](../.local/comparison-three-article-selection-c04-local-20261013/selection-core.py)

保存済み判定のみで再評価（モデル要求なし）：

```powershell
python -X utf8 .local/comparison-three-article-selection-c04-local-20261013/run-local.py --phase evaluate
```
