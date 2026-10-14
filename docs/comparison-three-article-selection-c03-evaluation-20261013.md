# 3記事選定案のC03限定・ローカル評価

実施日：2026-10-13（日本時間）。[提案書](comparison-three-article-selection-proposal-20261013.md)に基づく単一クラスタ評価。

**C03の19記事・171ペア・969組合せをローカル処理した。OpenAI API・外部API・埋め込みAPIはいずれも0回。最終状態は `needs_review`、採用は0組。**

C01・C02の結果とは別の保存先で実行し、前の成果物の不変を照合した。C03の全所属19記事を候補にした。現在のコアはF010の1件。ノイズと他クラスタは選定・モデル入力の対象にしていない。

## 実行方式と提案からの変更

| 項目 | 実行内容 |
| --- | --- |
| ローカル推論 | Ollama 0.5.7、DeepSeek-R1-14B-Q4_K:latest |
| 固定モデル | 2c8fc88a397e2753c57dc5fadf895fa7723d8cf5958f4c3bde34b7681c79b924 |
| 量子化 | モデル名にQ4_Kとあるが、OllamaメタデータではQ6_K（14.8B）。名称と実体を区別して記録 |
| 接続先 | http://127.0.0.1:11434 のみ。外部URLへのモデル要求・APIキーの読込みなし |
| 推論設定 | temperature=0、seed=42、num_ctx=8192。既存モデルの設定ファイルは変更しない |
| 構造化 | 保存本文全文をローカルモデルへ入力。原文引用を機械照合。失敗は1回だけ修復し、未確認の値は除外・保留 |
| 正規化 | C03向け固定用途辞書・原子的な比較項目ID。モデルの自由生成辞書とは区別 |
| ペア判定 | 全171ペアを8ペアずつローカルモデルで判定。入力プロフィールの主対象が未確定なら採用用comparableはunknown |
| 数値計算 | 元の1,536次元保存ベクトル・6条件の安定度を再利用。MMRと全組合せはPythonで計算 |
| 初期設定 | τ=0.55、MMR関連性重み0.75、R重み0.70／0.15／0.15、共通2項目以上・差異1項目以上 |

LLM工程のプロバイダーをOpenAIからローカルOllamaに変更し、正規化は固定辞書を使った。数値条件・全3ペア必須・3組織／3対象の条件は引き継いだ。モデル、入力テンプレート、辞書方式がC01・C02と異なるため、各結果を同じモデルの精度比較としては扱わない。

解析run_key：`3617f61f0501367f4adbbd6c68b102639b1a8b8df50ea031200eac1d1a69ca73`。ハッシュ・プロンプト版・モデルダイジェスト・実装版は[input-manifest.json](../.local/comparison-three-article-selection-c03-local-20261013/input-manifest.json)。

## 結果・保留理由

機械条件の代表状態：`insufficient_comparable_articles`。追加の原文・処理品質確認：`needs_review`。

- F010・F035・F175・F282・F349・F356・F398・F424・F430・F456・F705・F803・F863・F865・F887・F922・F932・F972・F983：修正後のローカルモデルのプロフィールにreadyは0件。比較対象・用途・項目が未確定の入力を類似度やMMRで自動採用しない。この結果だけでC03に比較可能な記事が存在しないとは判断できない。

- F010・F035・F175・F282・F349・F398・F430・F456・F705・F803・F863・F887・F922・F932・F972：対象候補名を1つ出しother_targetsが空である一方、状態をmultiple_targetsとする出力がある。対象名の候補と確定した比較対象は分け、原文確認が必要。

- F010・F035・F175・F282・F349・F356・F398・F424・F456・F705・F803・F863・F887・F922・F932・F972・F983：2項目未満の抽出が多く、本文にないという判定とローカルモデルが抽出できなかった可能性を区別できない。条件を緩めて不足項目を補っていない。

- F010・F865：インストール済みモデルのテンプレートは{{ .Prompt }}だった。初回chat形式の空プロフィールは別保存し、GGUF自身の特殊トークンを読み出してraw入力形式へ修正。モデルファイル・Ollama設定は変更せず、変更履歴を記録した。

- F010・F035・F175・F282・F349・F356・F398・F424・F430・F456・F705・F803・F863・F865・F887・F922・F932・F972・F983：モデル要求の接続先は127.0.0.1:11434のみ。OpenAI API・外部エンドポイント・APIキー読込み・追加埋め込みは使用していない。

**採用0組は、このローカル推論・辞書・初期条件で採用を確定できなかったという結果。C03に比較可能な3記事が存在しないことの証明ではない。**

## 基準方式との比較

| 方式 | 3記事 | 最低類似度 | 平均類似度 | 共通／差異 | 合否・理由 |
| --- | --- | --- | --- | --- | --- |
| centroid_top3 | F010・F282・F865 | 0.665870 | 0.683504 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| medoid_nearest2 | F175・F456・F865 | 0.686069 | 0.688577 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| maximum_minimum_similarity | F282・F349・F456 | 0.698707 | 0.710549 | 0／0 | needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference |
| proposed_mmr | なし | — | — | —／— | no_valid_triplet |

基準方式にも同じ本文・用途・対象・比較項目の条件を適用した。高い類似度だけでは対象不明・比較用途不明の判定を通過させない。

## 候補記事と構造化状態

| 記事 | 組織 | ローカルモデルの対象候補 | 状態 | 項目数 | 帰属確率／コア |
| --- | --- | --- | --- | --- | --- |
| [F010](https://prtimes.jp/main/html/rd/p/000000011.000128991.html) 生成AIを活用したAIコンタクトセンター『HARMONY Ver1.10』をリリース！ | ロジカル・アーツ株式会社 | HARMONY Ver1.10 | multiple_targets | 1 | 1.000000／コア |
| [F035](https://prtimes.jp/main/html/rd/p/000000779.000088829.html) 行政向け生成AI「QommonsAI」、J-LISフェア2026でエージェント版と行政専用AIアプリストア「Qommons ONE」を披露 — 自治体の定型業務を、職員の承認の基でAIが最後まで進める | Polimill株式会社 | QommonsAI 3.0 エージェント版 | multiple_targets | 1 | 0.516798／— |
| [F175](https://prtimes.jp/main/html/rd/p/000000004.000183002.html) お客様が1000人でも、一人ひとりに"覚えていてくれたんですね"と言われる。顧客専任AI「Teal」、9月24日正式ローンチ | 株式会社ClownPit | Teal | multiple_targets | 1 | 0.780491／— |
| [F282](https://prtimes.jp/main/html/rd/p/000000010.000076953.html) バックオフィスAIエージェント「カリスマAI」、Microsoft TeamsとLINE WORKSに対応 | 株式会社Automagica | カリスマAI | multiple_targets | 0 | 0.805808／— |
| [F349](https://prtimes.jp/main/html/rd/p/000000185.000019319.html) 【FAQ整備を全自動化】FAQの作成・見直し・更新をAIエージェントが対応 | アジアクエスト株式会社 | AQ-AI エージェント FAQ Builder | multiple_targets | 0 | 1.000000／— |
| [F356](https://prtimes.jp/main/html/rd/p/000000225.000033941.html) Ｈｍｃｏｍｍ、カスタマーハラスメント対策をAI Agent化 | Hmcomm株式会社 | VAAP Customer Protection Agent Suite | unknown | 1 | 0.588607／— |
| [F398](https://prtimes.jp/main/html/rd/p/000000002.000188608.html) リーガルテックサービス「Deemó LegalBase＋」に新プラン追加！ | 株式会社ディーモ | Deemó LegalBase＋ | multiple_targets | 1 | 0.516798／— |
| [F424](https://prtimes.jp/main/html/rd/p/000000016.000096990.html) いつもの業務マニュアルが、AI受付スタッフに。 | ＴＲＩＢＡＷＬ株式会社 | Kumion | unknown | 1 | 1.000000／— |
| [F430](https://prtimes.jp/main/html/rd/p/000000025.000128445.html) AI コールセンター「コルサポ」、コインパーキング業向けテンプレート α版を先行提供 ─ 精算機トラブル・料金案内・空車確認を 24 h 自動化 | 株式会社エクサテック | コルサポ | multiple_targets | 4 | 1.000000／— |
| [F456](https://prtimes.jp/main/html/rd/p/000000050.000062562.html) 「電話しなくても解決する」問診型AIエージェント「Navie（ナビィ）」正式リリース | 株式会社エーアイスクエア | Navie | multiple_targets | 1 | 1.000000／— |
| [F705](https://prtimes.jp/main/html/rd/p/000000191.000025498.html) ALSI 「InterPlay Elastic Framework」をアップデートし、自治体・企業の社会課題に対応する2つの新機能を追加 | アルプス システム インテグレーション株式会社 | InterPlay Elastic Framework | multiple_targets | 1 | 0.682197／— |
| [F803](https://prtimes.jp/main/html/rd/p/000000012.000100984.html) アイナビトラックのAIコンシェルジュ、大型アップデート ― AIエージェントとして用途の相談から在庫検索・査定・問い合わせまでを一つの会話で | 株式会社ステアリンク | AIコンシェルジュ（AIエージェント） | multiple_targets | 1 | 0.669002／— |
| [F863](https://prtimes.jp/main/html/rd/p/000000057.000064239.html) AI議事録「Rimo」、デジタル庁「デジタルマーケットプレイス（DMP）」に掲載 | Rimo合同会社 | Rimo | multiple_targets | 1 | 0.516798／— |
| [F865](https://prtimes.jp/main/html/rd/p/000000060.000019309.html) 「 AvaTwin Chatbot 」に音声認識オプションを追加ー 話すだけで、AI が自社資料に基づき回答 ー株主総会当日のリアルタイム質疑応答、窓口、採用、セールスまで多言語で対応。 | 株式会社グラッドキューブ | AvaTwin Chatbotの音声認識オプション | unknown | 4 | 0.616403／— |
| [F887](https://prtimes.jp/main/html/rd/p/000000087.000039866.html) 【株式会社アセンド】通話録音・AI文字起こし要約サービス「RecACE plus」がQTnetの「BBIQ光電話」「QT PRO 光電話」に対応 | 株式会社アセンド | RecACE plus | multiple_targets | 1 | 0.631116／— |
| [F922](https://prtimes.jp/main/html/rd/p/000000142.000090268.html) Scene Live、コミュニケーションにおける「認識のズレ」の可視化技術を開発し、特許を出願 | 株式会社Scene Live | Scene Liveの共通認識可視化技術 | multiple_targets | 0 | 0.568843／— |
| [F932](https://prtimes.jp/main/html/rd/p/000000165.000025663.html) カラクリの顧客対応AIエージェント「GeN」、さくらインターネットで自己解決率約80％を実現 | カラクリ株式会社 | Generative Navigator (GeN) | multiple_targets | 1 | 0.905462／— |
| [F972](https://prtimes.jp/main/html/rd/p/000000454.000059114.html) Web接客ツール「エルサイト」チャット画面にAIアシスト機能を追加 | 株式会社ミショナ | エルサイト | multiple_targets | 1 | 0.862347／— |
| [F983](https://prtimes.jp/main/html/rd/p/000000872.000059164.html) 【会社法務A2Z】企業実務に影響する重要法律の改正と会社法改正議論の現在地を解説した2026年10月号を発刊 | 第一法規株式会社 | multiple_targets | unknown | 1 | 0.516798／— |

対象名の候補はローカルモデルの申告を保存したもの。状態がreadyでなければ確定した比較対象として使用していない。

## 件数と失敗段階

プロフィール状態：`{"multiple_targets": 15, "unknown": 4}`。採用に使うペア比較可能性：`{"unknown": 171}`。

全969組合せ中、通過0件。次の理由は重複計上。

| 理由 | 組合せ数 |
| --- | --- |
| insufficient_comparison_axes | 969 |
| needs_review | 969 |
| no_meaningful_difference | 969 |
| similarity_below_threshold | 654 |
| unconfirmed_shared_purpose | 969 |

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
- 全171ペアのコサイン類似度を独立再計算（最大差3.33e-16）。保存本文入力ハッシュ、組織一意性、元入力ファイル不変を確認。
- 保存された22項目の引用が原文にあることを確認。意味の正確さとは区別。
- C01・C02の既存524ファイルのSHA-256不変を確認。
- 正解・保留の人による固定ラベルは未作成。誤採用率・誤除外率・正解率は算出していない。
- 単一クラスタ・単一ローカルモデルの試行。ローカルモデル一般の精度、他クラスタでの成立率、MMRの優位性は未評価。

## ローカル処理の使用量

| 項目 | 結果 |
| --- | --- |
| 工程内のローカルモデル要求 | 76 |
| 診断を含むローカル推論要求 | 79 |
| 工程内入力token | 207636 |
| 工程内出力token | 26161 |
| 工程内要求時間合計（秒） | 821.404 |
| OpenAI API要求 | 0 |
| 外部API要求 | 0 |
| 新規埋め込み要求 | 0 |
| API料金（米ドル） | 0 |

ローカルのGPU・電力等の計算費用は金額換算していない。プロトコル上の成功と記事内容の正しい判定は分ける。初回テンプレート・修復・診断の履歴も保存した。

## 保存ファイル

- [input-manifest.json](../.local/comparison-three-article-selection-c03-local-20261013/input-manifest.json)
- [article-profiles.json](../.local/comparison-three-article-selection-c03-local-20261013/article-profiles.json)
- [selection-profiles.json](../.local/comparison-three-article-selection-c03-local-20261013/selection-profiles.json)
- [normalization-dictionary.json](../.local/comparison-three-article-selection-c03-local-20261013/normalization-dictionary.json)
- [pair-judgments.json](../.local/comparison-three-article-selection-c03-local-20261013/pair-judgments.json)
- [pair-similarities.json](../.local/comparison-three-article-selection-c03-local-20261013/pair-similarities.json)
- [triplet-candidates.json](../.local/comparison-three-article-selection-c03-local-20261013/triplet-candidates.json)
- [selected-triplets.json](../.local/comparison-three-article-selection-c03-local-20261013/selected-triplets.json)
- [cluster-decisions.json](../.local/comparison-three-article-selection-c03-local-20261013/cluster-decisions.json)
- [evaluation.json](../.local/comparison-three-article-selection-c03-local-20261013/evaluation.json)
- [llm-usage.json](../.local/comparison-three-article-selection-c03-local-20261013/llm-usage.json)
- [source-review.json](../.local/comparison-three-article-selection-c03-local-20261013/source-review.json)
- [real-validation.json](../.local/comparison-three-article-selection-c03-local-20261013/real-validation.json)
- [rule-validation.json](../.local/comparison-three-article-selection-c03-local-20261013/rule-validation.json)
- [selection.html](../.local/comparison-three-article-selection-c03-local-20261013/selection.html)
- [run-local.py](../.local/comparison-three-article-selection-c03-local-20261013/run-local.py)
- [selection-core.py](../.local/comparison-three-article-selection-c03-local-20261013/selection-core.py)

保存済み判定のみで再評価（モデル要求なし）：

```powershell
python -X utf8 .local/comparison-three-article-selection-c03-local-20261013/run-local.py --phase evaluate
```
