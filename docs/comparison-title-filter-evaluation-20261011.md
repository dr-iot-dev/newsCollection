# タイトル除外・カテゴリタグ不要条件による生成AI資料選択の実評価（2026-10-11）

状態：完了。10ペア不成立による探索不成立。

実行ID：`e4470361-be93-456f-8908-29c747ec5079`。評価スキーマ：`evaluation_pair_titles_genai_20261011_v3`。

距離上位10ペアはいずれも同一製品「ChatSense」の機能更新・提供予告の組合せと判定された。異なる製品を選ぶための比較ペアが成立せず、群B抽出・第三資料検証には進まなかった。

## 最終結果

| 工程 | 件数・状態 |
| --- | --- |
| 初期候補の確認 | 51 |
| 初期タイトル除外 | 34 |
| 初期補充の本文・タイトルにカテゴリ名なし | 7 |
| 初期資料 | 10 |
| 特徴キーワードK | 50 |
| 完了した語別検索 | 50 |
| 語別結果行 | 5762 |
| 異なる原文URL | 4814 |
| 検索3語以上（タイトル除外前） | 172 |
| 検索3語以上からタイトル除外 | 27 |
| 本文取得候補（タイトル除外後） | 145 |
| 本文確認 | 145 |
| 資料群A | 90 |
| 群Aのうち生成AIタグなし | 19 |
| 埋め込み | 90件・1536次元 |
| 全ペア距離 | 4005 |
| 完了ペア | 10 |
| 第三資料の検証 | 0 |
| 採用資料 | 0 |
| 最終状態 | exhausted / ten_pairs_completed_without_comparison |

本文確認後の採否：`accepted` 90件、`fewer_than_three_keywords` 55件。

語別検索のページ記録は162ページ。うち38ページは同じ検索式で取得済みの正常応答を継承した。
AI記録は21回（資料別抽出の継承0回、この実行の新規21回）。外部呼出しの予約累計521回は管理値であり、成功したHTTP取得数ではない。

## 適用した選択条件

取得方針は `product-service-titles-v6-initial-category-text-no-tag`。記事の「生成AI」タグは要求しない。指定カテゴリは初期一覧とKの抽出文脈に用いる。

初期資料・検索候補・群Aでは、タイトルに次の語を含む資料を除外する：調査、事例、アンケート、ランキング、レポート、ホワイトペーパー、白書、セミナー、ウェビナー、勉強会、講演、対談、インタビュー、イベント開催、展示会、書籍、出版、刊行、受賞、ベストセラー、取材、登壇、交流会、トークシリーズ、開催、大会、決算、増収、増益、声を公開、説明会、コラム、論文、論考、ガイドブック、寄稿、出展、設立、事業重点化、スポンサー契約。NFKCとNUL・置換文字の除去はタイトル照合用に限り、原文を保持する。

カテゴリ一覧の表示は10件で、除外後は初期数が不足したため、同じカテゴリ名の公開検索で補充した。補充記事は主要本文・タイトルにカテゴリ名があることも確認する。これは初期補充だけの条件であり、群Aにカテゴリ名の出現やタグ所属を追加条件にしていない。初期補充の検索結果をKのヒット語へ加算しない。

Kの各語で最大150件のID・URL・タイトルを保存し、URLごとの異なる語数を集計する。3語以上かつタイトル除外を通った候補を本文確認し、本文3概念一致・品質・重複排除で群Aを最大100件に固定する。

全資料の実ベクトルと全ペア距離を保存し、距離順にペアを選ぶ。群B内の第三資料をペアへの平均距離順に試し、3項目以上で各項目2/3資料以上の特徴を確認し、独立検証を通れば採用する。探索不成立は10ペア完了時だけであり、通信・モデル・予算中断はペア不成立に数えない。

## 初期10資料

| No. | タイトル | 資料ID |
| ---: | --- | --- |
| 1 | [【日本・台湾で特許取得】サイカルトラスト、「SBOM（ソフトウェア部品表）」とブロックチェーンを利活用した機器の「真正性証明」技術を権利化。グローバルサプライチェーンのセキュリティ課題を解決へ](https://prtimes.jp/main/html/rd/p/000000196.000044818.html) | `17ec6cf9-6994-48fc-8de8-a2502bd8519f` |
| 2 | [法人向け「Notebook AI」、スキャンPDFからスライドを自動生成可能に](https://prtimes.jp/main/html/rd/p/000000418.000073671.html) | `ee8fcaa2-76cf-4bbd-a301-cd9eb9200996` |
| 3 | [「ガクチカのためだけで終わらせない。」AI時代のNEO長期インターンプラットフォーム「BE INTERN」が先行公開！](https://prtimes.jp/main/html/rd/p/000000003.000166564.html) | `c2e11ad8-5193-473e-88a7-6eca8a7b7539` |
| 4 | [GenerativeX、AIを活用したサイバーセキュリティ支援サービスを提供開始](https://prtimes.jp/main/html/rd/p/000000049.000124664.html) | `2e4dc15e-6cf3-4c93-8773-aebb465911db` |
| 5 | [金融機関で培った診断・認証の知見で、AI時代の攻撃に備える「セキュリティ相談窓口」の開設に関するお知らせ](https://prtimes.jp/main/html/rd/p/000000080.000117557.html) | `f89c88ee-fc2c-4738-81fd-4352b3e6c4e7` |
| 6 | [【AlphaDrive高知】非エンジニア向けの「AX相談窓口」を開設](https://prtimes.jp/main/html/rd/p/000000388.000033909.html) | `d9f56d8e-0db2-4ad6-94cb-302c39f135a2` |
| 7 | [ウォルターズ・クルワー、医療向け生成AI「UpToDate Expert AI」の国内提供を開始。AI回答の信頼性と透明性を確保](https://prtimes.jp/main/html/rd/p/000000001.000191779.html) | `5312e85f-6868-4c78-b2ef-d6550acb43d5` |
| 8 | [年間約８万件の実務知見をAIへ。ミトラグループ、担保適格性判定バーティカルAIの実証を開始](https://prtimes.jp/main/html/rd/p/000000036.000040495.html) | `2c70c48f-ed42-4cff-aab8-c55bdbf9925c` |
| 9 | [平成ギャルになれる生成AIフォトブース、ギャル雑誌『egg』とコラボして渋谷に初登場](https://prtimes.jp/main/html/rd/p/000000216.000020107.html) | `59aebc1c-9e77-44cf-aed5-2e7b31f3915a` |
| 10 | [ギブリー、AI時代のサイバーセキュリティ人材を定義する「サイバーセキュリティスキル標準 2026」を公開](https://prtimes.jp/main/html/rd/p/000000413.000002454.html) | `fbdc98b7-64e4-4466-9a63-08fb7228e499` |

一覧表示では置換文字を省略した。凍結タイトル・本文hash・原文引用は監査JSONに保持している。

## Kの全語

| No. | キーワード |
| ---: | --- |
| 1 | SBOM |
| 2 | 脆弱性データベース |
| 3 | 情物不一致 |
| 4 | 情物一致 |
| 5 | 事前証明 |
| 6 | ゼロトラスト |
| 7 | フロンティアAI |
| 8 | ディープフェイク |
| 9 | AIオーケストレーション |
| 10 | AI認証局 |
| 11 | ISO 26345 |
| 12 | セキュリティの高い環境 |
| 13 | 社内データの追加学習機能 |
| 14 | メンバーの一括管理機能 |
| 15 | フォルダ＆ドラッグ機能 |
| 16 | レッドチーミング |
| 17 | RAGシステム |
| 18 | AIエージェント |
| 19 | アラート選別 |
| 20 | ログ要約 |
| 21 | 生成AI利用ガイドライン |
| 22 | ディープフェイク対策 |
| 23 | 横断的に診断 |
| 24 | 個人情報の所在把握 |
| 25 | 流出経路の点検 |
| 26 | コード診断 |
| 27 | フィッシング文面 |
| 28 | OSINT |
| 29 | パスキー |
| 30 | Completion Cost Collapse |
| 31 | Full-Product Launch |
| 32 | AI Orchestration |
| 33 | Field Intelligence |
| 34 | 収益進化AIシステム |
| 35 | AXアーキテクト |
| 36 | 自然言語処理 |
| 37 | 執筆・査読 |
| 38 | 72項目の不適格基準 |
| 39 | 基準×確認書類×該当箇所×確認キーワード |
| 40 | 構造化抽出 |
| 41 | 人へ回付 |
| 42 | 要注意業者リスト |
| 43 | 表記ゆれ |
| 44 | AI駆動開発 |
| 45 | 共通ID |
| 46 | パブリックデータ |
| 47 | 顔写真 |
| 48 | 表紙風ビジュアル |
| 49 | デジタルデータ |
| 50 | スタイル |

## ペアの判定

| 順位 | 距離 | 左資料 | 右資料 | 比較項目数 | 群B | 第三資料試行 | 結果 |
| ---: | ---: | --- | --- | ---: | ---: | ---: | --- |
| 1 | 0.01801951 | 法人向け「Notebook AI」、自分でメモを追加・編集できる機能を提供予定 | 法人向け「Notebook AI」、社内データを可視化する機能を強化 | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 2 | 0.02021874 | 法人向け生成AI「ChatSense」、Gemini・ClaudeでもWeb検索を利用可能に | 法人向け生成AI「ChatSense」、Claudeでも「Deep Research」を利用可能に | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 3 | 0.02451833 | 法人向け「Notebook AI」、スキャンPDFからスライドを自動生成予定 | 法人向け「Notebook AI」、スキャンPDFからスライドを自動生成可能に | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 4 | 0.02682154 | 法人向け「Notebook AI」、社内資料をマインドマップで自動整理する機能をリリース予定 | 法人向け「Notebook AI」、質問の意図を理解して社内資料を高精度検索 | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 5 | 0.02708837 | 法人向け「Notebook AI」、Studio機能をさらに便利に | 法人向け「Notebook AI」、社内データを可視化する機能を強化 | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 6 | 0.02871424 | 法人向け「Notebook AI」、スキャンPDFからスライドを自動生成予定 | 法人向け「Notebook AI」、社内資料をマインドマップで自動整理する機能をリリース予定 | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 7 | 0.02992468 | 法人向け生成AI「ChatSense」、Gemini・ClaudeでもWeb検索を利用可能に | 社内向け生成AI基盤「ChatSense」、Gemini・Claudeモデルでもコードインタープリター搭載 | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 8 | 0.03078788 | 法人向け生成AI「ChatSense」、Gemini・ClaudeでもWeb検索を利用可能に | 法人AIサービス、Claude・Geminiでの社内データ質問回答に対応予定 | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 9 | 0.03239784 | 法人向け「Notebook AI」、社内資料からマインドマップを自動生成する機能をリリース | 法人向け「Notebook AI」、社内資料をマインドマップで自動整理する機能をリリース予定 | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |
| 10 | 0.03283181 | 法人向け「Notebook AI」、自分でメモを追加・編集できる機能を提供予定 | 法人向け Notebook AI サービス、AI回答をワンクリックでメモ保存する機能をリリース | 0 | 0 | 0 | pair_not_comparable_or_axes_insufficient |

1位の判断理由：Both releases describe updates/features for the same product’s same area: they each reference 「当社が提供する法人向け生成AIエージェント「ChatSense」のNotebook機能」, with one announcing a planned memo add/edit capability and the other announcing diagram orientation/shape selection expansion within the Notebook feature. These are complementary feature announcements for the same product rather than distinct alternatives a reader would select between.


2位の判断理由：Both releases are announcements about new capabilities becoming available within the same product, 「ChatSense」, from the same organization. One adds Web検索 for Gemini/Claude chats, the other adds Deep Research for Claude/Gemini chats; these are feature updates for the same offering rather than distinct alternatives a reader would select between.


3位の判断理由：2つのリリースは別製品の選択ではなく、同一の提供元（株式会社ナレッジセンス）の同一製品（「ChatSense」）のNotebook機能に関する『近日中にリリース予定』という予告と、『生成できるようにした』という提供開始の告知であり、代替比較の読者選択タスクにならないため。例えば、片方は「近日中にリリース予定」、もう片方は「生成できるようにしたことをお知らせします」と同一機能の前後を述べている。


4位の判断理由：両方のリリースは同一製品（ナレッジセンス提供の「ChatSense」の「Notebook機能」）について、別の機能（マインドマップ自動生成の近日リリース予定／高精度検索の実装済み）を述べています。よって“どちらの製品を選ぶか”という選択タスクではなく、同一製品の機能アップデート情報同士であり、製品比較としては不適切です。


5位の判断理由：Both releases describe feature updates to the same product’s same area (“ChatSense”の“Notebook機能”). They are not distinct products or alternatives for a reader to choose between; they are complementary enhancements within the same offering.


6位の判断理由：Both releases describe planned new capabilities within the same product (“「ChatSense」のNotebook機能”), not alternative products/services to choose between; they are complementary feature announcements for the same selection task rather than distinct options.


7位の判断理由：両方とも同一製品「ChatSense」の機能追加（アップデート）に関する発表であり、異なる代替製品・プラン・提供主体の選定比較ではないため、比較ペアとしては不適切です。


8位の判断理由：両方とも同一の法人向け生成AIエージェント「ChatSense」についての機能追加/提供予定の告知であり、別プロダクト同士の選定比較ではありません。さらに一方は「Web検索」を、もう一方は「追加学習AI」でのモデル選択（Claude/Gemini）という別機能領域を扱っており、代替関係の比較（どちらを選ぶか）ではなく同一製品の機能アップデート情報の組み合わせです。


9位の判断理由：2つのリリースは同一の提供元・同一プロダクト（「ChatSense」の「Notebook機能」）について、同一機能（資料内容を階層化しマインドマップとして自動生成）の「リリースした」告知と「近日中にリリース予定」告知であり、同一プロダクトの計画と後日の提供開始アナウンスの関係に当たるため、代替案としての比較（どちらを選ぶか）になりません。


10位の判断理由：Both releases describe the same offering—株式会社ナレッジセンスの「ChatSense」のNotebook機能—covering different feature updates (one planned, one released) rather than distinct alternatives a reader would select between.


10位を超えるペアを試していない。群B到達：False。比較できる3資料が成立せず、記事生成は行っていない。

## 成果の引継ぎ・途中試行

タイトル正規化、初期補充の関連性確認、イベント・紹介記事・出展・会社告知の除外を実資料で補強した。途中試行は0ペアの段階で保存し、探索不成立とは扱っていない。

| 途中実行 | 保存状態 |
| --- | --- |
| `23f47d2a-df26-4a12-a9b7-9addff1998d1` | 初期6件・K未確定。NUL置換文字で調査の除外が漏れる問題を修正 |
| `3753bd21-2719-4f01-a15a-9860e5349a0f` | 初期10件・K21語。初期補充の関連性確認を追加 |
| `713ec674-2e49-4952-9b1e-f91af6cb683a` | 初期10件・K31語。イベント・業績・紹介タイトルを追加除外 |
| `eadd4833-b823-4d33-8daf-92bbae552973` | 初期10件・K50語。出展・設立・事業重点化を追加除外 |
| `7044f84b-f1b4-4e66-871e-e7fc76fb6103` | 初期10件・K50語。スポンサー告知と明確な一般語を追加除外。0ペアで保存 |

最終実行へは、条件を通る9初期資料のsnapshot・body hashを引き継ぎ、残り1資料を補充した。一般語除外の文脈が変わるため、10資料のキーワードをすべて新規に抽出した。旧Kの統合結果、群A、ベクトル、距離は引き継いでいない。完全一致する検索式で取得済みの正常な語別検索メタデータは、元実行IDとsnapshotを記録し、語IDを対応させて語数とタイトル除外を再計算して用いた。

途中実行のK統合でAI応答待ちの中断が起きたため、評価用の読み取り待ち時間を90秒から300秒へ延長した。最終実行でも300秒を用いた。中断をペア不成立へ加算していない。

## 検証と保存ファイル

最終の関連159テストが通過した。保存された全語の結果から記事別語数・候補順位・タイトル除外を再計算し、原文引用・本文hash・全ベクトル・全ペア距離・終了条件の整合を確認した。今回の10ペアは群Bの抽出・第三資料の検証に到達しておらず、その工程の実評価件数は0件である。

- [最終概要](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/summary.json)
- [整合検証](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/verification-summary.json)
- [監査JSON・採用資料の本文・資料ID・根拠](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/audit.json)
- [AI実行記録](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/ai-runs.json)
- [初期資料の採否と除外語](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/initial-selection.csv)
- [採用初期10資料](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/initial-documents.csv)
- [Kの全語・採用理由](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/keyword-set.csv)
- [語別検索の全結果](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/keyword-search-results.csv)
- [語別保存件数](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/keyword-search-summary.csv)
- [記事別語数・除外語](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/article-keyword-counts.csv)
- [資料群AのID・URL・タイトル](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/group-a-documents.csv)
- [全ペア距離](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/pair-distances.csv)
- [ペアの判定理由](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/pair-decisions.csv)
- [第三資料の距離順](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/third-distances.csv)
- [比較項目の充足数](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/coverage.csv)
- [継承した初期資料のhash・再抽出方針](../.local/pair-genai-title-filter-evaluation-20261011/e4470361-be93-456f-8908-29c747ec5079/seed-provenance.json)

記事生成・WordPress送信・運用への再配備は実施していない。資料選択の完了結果を保存した。
