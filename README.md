# News Weave

PR TIMESの原資料から比較記事を作り、1本ずつ検証する7段階のシステムです。

1. 商品サービス・AI／IoT・タイトル除外条件を満たす記事を取得。
2. PR TIMES企業IDごとに公開日時が最新の1記事を選択。
3. 選択した記事のタイトル・本文から埋め込みを計算。
4. UMAP → HDBSCANでクラスタリング。
5. 各クラスター内で、元の埋め込みベクトルの重心に近い3記事を選択（AIは使用しない）。
6. 3資料全文から指定書式の比較記事を生成。
7. 別モデルが比較記事1本・3資料全文・生成時のモデル指示を個別検証。不備があれば同じ生成モデルで1回だけ修正し、再検証の結果を最終結果とする。

生成本文が「比較不適（公開不可）」の場合は、評価・修正を呼ばず即座に最終不適とします。この場合の点数は未採点（null）です。再検証で不備が残っても修正を繰り返しません。

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

collectは公開記事のGET、runは埋め込み・生成・検証のAPIを実行します。3記事の選択はローカルで計算します。
.envは自動読込しません。AI_API_KEY（またはOPENAI_API_KEY）とPIPELINE_DATABASE_URLは実行環境へ設定します。
生成と検証に同じモデルを指定することはできません。

取得済みHTMLは、url・htmlを持つJSON配列からimport-htmlで読み込めます。
中断した実行はresume <run_id>で再開できます。完了済みの同一実行の処理は繰り返しません。
修正要求は送信前に記録します。応答を保存できなかった場合は停止し、resumeでも修正要求を再送しません。修正版を保存済みなら再検証から再開します。
新しいrunでは②で選び直し、③で埋め込みを計算します。実行間の埋め込みキャッシュはありません。

## DBとDocker

DBはarticles・runs・run_articles・comparisons・drafts・verificationsの6テーブルです。
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
