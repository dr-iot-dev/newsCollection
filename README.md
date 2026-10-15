# News Weave

PR TIMESの原資料から比較記事を作り、1本ずつ検証する7段階のシステムです。

1. 商品サービス・AI／IoT・タイトル除外条件を満たす記事を取得。
2. PR TIMES企業IDごとに公開日時が最新の1記事を選択。
3. 選択した記事のタイトル・本文から埋め込みを計算。
4. UMAP → HDBSCANでクラスタリング。
5. 各クラスターの元ベクトルの重心に近い最大30記事をGPT-4.1へ渡し、本命・予備の3記事組を最大2組選択。
6. 本命3資料全文をGPT 6.1 Solで判定し、APPROPRIATEなら記事生成。INAPPROPRIATEなら予備があるときだけ予備で試行。
7. 別モデルが比較記事1本・3資料全文・生成時のモデル指示を個別検証。不備があれば同じ生成モデルで1回だけ修正し、再検証の結果を最終結果とする。

生成時にAPPROPRIATEになった記事は必ず別モデルで独立検証・採点します。生成不適の組には記事本文を作らず、理由を保存し採点はnullです。選定不可、生成時の自己判定、独立検証の最終採否を区別します。検証不適・要確認は同じ3資料で1回だけ修正・再検証し、予備への切り替えは初回本命の生成不適の場合だけです。再検証で不備が残っても修正を繰り返しません。

[新設計と最小DBスキーマ](docs/seven-stage-system-design-20261015.md)が現行の仕様です。
実装を始める前に `python maintenance/check_environment.py` を実行してください。環境準備・データ移行は[専用手順](maintenance/setup-and-migration.md)に分離しています。

## ローカル実行

```powershell
python -m pip install ".[dev]"
$env:AI_API_KEY = "APIキーを環境変数から設定"
news-weave --database sqlite:///.local/pipeline-v2.sqlite init
news-weave --database sqlite:///.local/pipeline-v2.sqlite collect --search-pages 2
news-weave --database sqlite:///.local/pipeline-v2.sqlite run
news-weave --database sqlite:///.local/pipeline-v2.sqlite list
news-weave --database sqlite:///.local/pipeline-v2.sqlite export <run_id> --output .local/results
```

collectは公開記事のGET、runは埋め込み・選定・生成・検証のAPIを実行します。選定の入力を最大30記事に絞る順位はローカルで計算し、その全文からAIが本命・予備を選びます。
.envは自動読込しません。AI_API_KEY（またはOPENAI_API_KEY）とPIPELINE_DATABASE_URLは実行環境へ設定します。
生成と検証に同じモデルを指定することはできません。

取得済みHTMLは、url・htmlを持つJSON配列からimport-htmlで読み込めます。
中断した実行はresume <run_id>で再開できます。完了済みの同一実行の処理は繰り返しません。
修正要求は送信前に記録します。応答を保存できなかった場合は停止し、resumeでも修正要求を再送しません。修正版を保存済みなら再検証から再開します。
新しいrunでは②で選び直し、③で埋め込みを計算します。実行間の埋め込みキャッシュはありません。選定モデルと3指示も実行開始時に固定し、保存済みの選定・生成を再開時に呼び直しません。

既定のモデルは選定`gpt-4.1-2025-04-14`、生成`gpt-6.1-sol`、検証`gpt-4.1-2025-04-14`です。`run --selection-model ... --selection-candidate-limit 30 --generation-model ... --verification-model ...`で設定できます。候補上限は3〜30に限定します。

既存DBはカラム構成が変わるため、そのまま更新せず保持します。新しい接続先に原資料だけを移す場合は、次の明示的な移行を使います。過去の実行・記事・判定は元DBに残ります。

```powershell
python -m maintenance.migrate_ai_selection --source .local/pipeline-v2.sqlite --database sqlite:///.local/pipeline-ai-selection.sqlite
news-weave --database sqlite:///.local/pipeline-ai-selection.sqlite run
```

## DBとDocker

DBはarticles・runs・run_articles・comparisons・drafts・verificationsの6テーブルです。comparisonsに候補・本命・予備・選定応答、draftsに本命/予備と生成判定・理由を保持します。
SQLiteでもPostgreSQLでも同じ構造を使います。[PostgreSQL DDL](schema/pipeline.sql)を同梱します。
既存のDBスキーマが一致しない場合は初期化を拒否します。

```powershell
docker compose build worker
docker compose up -d db
docker compose run --rm worker news-weave init
docker compose run --rm worker news-weave collect --search-pages 2
docker compose run --rm worker news-weave run
docker compose run --rm test
```

新Composeのプロジェクト名はnews-weave-v2です。新しいDB・ボリュームを使用します。
既存の稼働環境の停止・新構成の本番起動は、自動では行いません。

## 開発検証

```powershell
pytest
ruff check app tests
```

テストではAPIをモックし、UMAP／HDBSCANだけをローカルで実行します。
判定は適切・不適・要確認と絶対評価点です。減点前の基本点は、合格水準を明らかに超える記事を80点以上、明らかに下回る記事を50点以下とするようモデルへ指示します。
書式を含む不備・指示違反を1つでも確認した記事は不適・50点以下とするよう検証モデルへ指示し、生成モデルにも同じ評価基準を伝えます。
比較表で3対象中2対象以上に具体的な情報がない項目は、1項目につき10点を基本点から累積して減点し、下限を0点とします。未記載そのものを指示違反とはせず、点数だけで採否を変えません。


## 選定後に停止する実行

`run --stop-after select` または `resume <run_id> --stop-after select` は、⑤の選定を保存し、`step=generate` の状態で停止する。`complete` とは区別する。停止済みの同じ実行へ再度指定してもモデル呼出しは繰り返さず、通常の `resume <run_id>` で保存済み選定から生成・独立検証へ進める。

明示的なユーザー指定でキーワード検索を行う実行スクリプト向けに、`parse_article(..., require_domain=False)` でAI/IoT条件だけを解除できる。商品サービス・公式HTML・企業ID・タイトル除外の検査は維持し、通常の `collect` と既定の解析条件は変更しない。

[電子工作・モバイル2,000件の実行記録、比較記事、コスト、画像](experiments/prtimes-electronics-mobile-2000-20261015/README.md)は、個別依頼の実行記録であり通常運用の仕様ではない。
