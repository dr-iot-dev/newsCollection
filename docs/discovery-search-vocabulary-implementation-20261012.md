# 検索語彙Discoveryの実装と実行方法

仕様: [discovery-search-vocabulary-v2](discovery-search-vocabulary-spec-20261012.md)。

3〜5件の抽出済み記事から、同分野の別製品・別サービスを通常の語句検索で探すための基本概念を生成する。契約は `DiscoverySearchVocabularyV2`、AI実行ロールは `discovery_vocabulary`。各概念は label、definition、aliases、4層のlayer、priority、origin、source_article_ids、reasonを持つ。

仕様第8節のモデル非依存プロンプトをそのまま使用する。記事別候補の和集合、基本概念への整理、4層による分野補完、真の同義語の整理を1回のモデル呼出で行う。通常1呼出、受信検査に失敗した場合だけ最大1回修復する。30〜50は探索の目安として指示し、件数・層のノルマは検査へ持ち込まない。

## 設定

既存のDBとAI provider設定を使用する。`AI_DISCOVERY_VOCABULARY_MODEL` を設定すると専用モデルを使う。空の場合は `AI_COMPARISON_PLANNER_MODEL` を使用する。モデル名は契約・プロンプトに固定しない。

- `AI_DISCOVERY_VOCABULARY_MAX_INPUT_CHARS`: 既定200000。
- `AI_DISCOVERY_VOCABULARY_MAX_OUTPUT_TOKENS`: 既定16000。
- `--call-budget 1`: 修復を行わず1回だけ実行。
- `--call-budget 2`: 既定。必要な場合だけ1回修復。

## Discovery単独の実行

入力JSONは仕様の `domain_hint` と `articles` 形式。`article_id` は任意の一意文字列でよい。JSON経路では記事をDBへ登録する必要はない。履歴とAI実行記録はDBへ保存する。

```powershell
news-weave discovery-vocabulary discover --input docs/examples/discovery-vocabulary/seeds.json --output .local/discovery-vocabulary
```

登録記事を使う場合は、同分野の3〜5件を明示する。

```powershell
news-weave discovery-vocabulary discover --item <UUID-A> --item <UUID-B> --item <UUID-C> --domain-hint "IoT製品・サービス" --output .local/discovery-vocabulary
```

登録記事経路では、有効かつapprovedのソースに属する、現在版の抽出済み記事を使う。重複記事と未抽出の記事は選択対象へ入らない。

実行結果に `run_id`、`status`、語彙を表示する。成功時は `ready`、失敗時は `failed` とエラーコードを返し、終了コード2にする。不正入力や履歴検査エラーは終了コード1。候補だけで実行が完了する。

```powershell
news-weave discovery-vocabulary show <run_id>
news-weave discovery-vocabulary export <run_id> --output .local/discovery-vocabulary-export
```

`show` は label・aliases・layer・priority・origin を表示する。エクスポートは次の3ファイル。

- `vocabulary.json`: 仕様どおりのJSONオブジェクト。
- `candidates.csv`: 全候補と定義、由来、優先理由。UTF-8 BOM付き。
- `audit.json`: 入力、語彙、ハッシュ、モデル、provider、プロンプト版、契約ハッシュ、方針版、検索方針版、AI実行IDと状態。

失敗時は監査JSONだけを出力する。モデルや入力を変えた評価は別の出力ディレクトリを指定する。

同じ入力・モデル・プロンプト・契約・方針で再実行すると、検証済み履歴を再利用する。失敗した実行は同じコマンドで再試行でき、失敗したAI実行IDも保持する。履歴の内容とハッシュ、成功したAiRunのロール・モデル・provider・プロンプト版・入力ハッシュ・出力を検査する。

## 後段検索

`label OR aliases` の語句一致と、別条件の `domain_terms` のOR一致を組み合わせる。NFKC正規化、casefold、英字境界を使う。日本語の複合語は部分一致する。例えば「遠隔監視」は「監視」に一致するが、RapidAPIはAPIに一致しない。同義語が同時に一致しても1概念として数える。definitionやreasonは検索文字列に使用しない。

次の例はAI・DBを使わず実行できる。JSONは実在記事ではない説明用データで、語彙例は仕様の部分出力例である。

```powershell
news-weave discovery-vocabulary search --vocabulary docs/examples/discovery-vocabulary/vocabulary.example.json --articles docs/examples/discovery-vocabulary/held-out-articles.json
```

実行後の語彙で登録済みの記事を検索する場合:

```powershell
news-weave discovery-vocabulary search --vocabulary .local/discovery-vocabulary/vocabulary.json --registered --exclude <UUID-A> --exclude <UUID-B> --exclude <UUID-C> --output .local/discovery-vocabulary/search-results.json
```

`--exclude` は種資料を結果から除くために指定する。`--no-domain-filter` は既に同分野へ絞った記事集合を検索する場合に使う。検索結果は一致した名称・同義語、概念数、層数、highの概念数を返し、high数、層数、概念数の順で順位付けする。

## 受入確認

JSONの型・必須項目・余分な項目、文字数、括弧と質問表現、IDと名称の重複、labelとaliasesの重複、同義語を別IDへ重複登録した場合、参照記事ID、originと参照数、highの先行順を検査する。IDは大小文字を区別する。名称・検索語だけに検索用正規化を適用する。

仕様で指定された修飾付きの名称、監視・管理・連携の相互混入、保存期間・LTE・メール・見積などの誤った同義語は修復対象にする。それ以外の意味上の同義関係、一般性、layerとdefinitionの整合は、生成結果の受入確認でも点検する。文脈依存の意味判断を文字列規則で網羅できるとは扱わない。

1記事だけに出る概念、未出現の同義語、domain_expansion、データなどの広い語を受理する。記事での頻度、引用中の語句一致、過半数、shared_search_candidatesやGENERIC_SEARCH_FORMSを採用条件に使わない。比較表のDynamicAxisとは契約・キャッシュ・実行ロールを分け、値抽出や比較順位をこの工程に含めない。

`tests/unit/test_discovery_search_vocabulary.py` は仕様の回帰例、50を超える候補と少数候補、独立した種資料外テスト記事での再現率・適合率、英字境界、概念の重複カウント防止、履歴の再利用と改変拒否、CLI、現在版・approvedの登録記事読み込みを扱う。検索評価は説明用コーパスに対する決定的な回帰テストであり、実際のモデルが生成した語彙や実記事検索の品質評価とは区別する。

実装入口:

- `app/contracts/discovery_search_vocabulary_v2.py`
- `app/ai/search_vocabulary_prompts.py`
- `app/core/discovery_search_vocabulary.py`
- `app/orchestration/discovery_search_vocabulary.py`
- `app/discovery_vocabulary_cli.py`

モデル引き継ぎ用のプロンプト・Schemaは `python -m tools.export_model_contracts` で `docs/model-contracts.json` に出力する。


## 検証結果（2026-10-12）

本番と独立したテスト用コンテナ・一時PostgreSQLを使用した。全テストは983件通過、1件スキップ。Discovery専用の83件を含む。Ruffのコード検査、変更したPythonファイルの書式検査、mypyによるapp全126ファイルの型検査が通過した。CLIの説明用JSON検索はD・Eだけに一致し、分野違いのXと企業紹介のYを除外した。

実モデルAPIによる生成品質・実記事コーパスでの再現率と適合率の評価は、この実装検証には含めていない。


## 実記事による実行確認

実装時の模擬応答によるテストの後、公開IoT実記事5件をOpenAI gpt-5.2へ渡して50候補を生成し、保存済み実記事220件のDBに対して候補語のカウントを実行した。その後、Extractionの指定タイトル除外条件により175件を除外し、その時点では45件を検索対象として再集計した。続いて記事を追加取得し、現在は除外後200件の検索対象を確保して再集計した。[現在の実行結果と確認表](extraction-word-count-results-20261012.md)、[Extraction仕様](extraction-word-count-spec-20261012.md)を参照。


Extractionは2026-10-13にタイトル除外を103語へ増やし、AI／IoTの分野条件を追加した。現在の対象200件の結果と語彙の使い方は[Extraction仕様](extraction-word-count-spec-20261012.md)と[実行結果](extraction-word-count-results-20261012.md)を参照。
