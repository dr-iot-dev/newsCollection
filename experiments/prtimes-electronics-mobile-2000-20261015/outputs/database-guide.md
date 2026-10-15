# DBの使い分け

この実行は「電子工作」「モバイル」のキーワード検索を対象とする。公式の種類「商品サービス」（01）と111語のタイトル除外を維持し、ユーザー指定によりAI/IoTの必須条件を外す。検索結果のタイトルだけで商品種別を推定せず、公式HTMLで確認する。

## 今回の新DB

`C:\Users\driot\Documents\Codex\2026-10-15\pr-times-2000-db-db-db\outputs\newsweave-electronics-mobile-2000-20261015.sqlite`

接続URL:

```text
sqlite:///C:/Users/driot/Documents/Codex/2026-10-15/pr-times-2000-db-db-db/outputs/newsweave-electronics-mobile-2000-20261015.sqlite
```

現行AI選定対応スキーマの6テーブルを新規作成した。旧DBの実行結果は取り込まず、指定キーワードで得た原資料を保存する。既存の公式HTMLスナップショットを再利用した場合も、新しい条件で解析し直す。本文中のAI/IoT用語がない原資料の`domains`は空配列となる。

収集完了後は企業IDごとの最新1記事を残して埋め込み、UMAP/HDBSCANでクラスタリングし、各クラスターの重心に近い最大30記事の全文をGPT-4.1へ渡す。2,000件は企業ごとの整理前の適格原資料数であり、埋め込み対象件数はこれより少なくなる。

今回の停止位置は⑤完了後である。`runs.step = generate`は⑥の開始待ちを意味する。実行全体の`complete`とは区別し、`run-manifest.json`の`selection_complete`と`selections.json`を確認する。

新DBでは`comparisons`に候補ID・本命・予備・選定結果を保存する。`drafts`と`verifications`が0件であることを完了時に確認する。

## 収集監査DB

同じ出力ディレクトリの`collection-audit-20261015.sqlite`に検索ページ・検索候補・読み込んだ公式HTMLとハッシュを保存する。

- `search_pages`: キーワードごとの検索API応答と取得時刻。
- `candidates`: URLで重複を排除した検索結果。2語に共通するURLは最初に保存した語へ帰属する。
- `snapshots`: 本文確認したURL、HTML、SHA-256、元HTMLの取得時刻、採否、対応する新DB記事ID。`error`欄は今回の取得元区分（`live` / `stored_official_snapshot`）として使用する。

タイトル除外は本文取得前にも適用するため、タイトルで除外したURLは`candidates`にのみ存在する。HTTP取得に失敗した記事は2,000件に含めない。検索結果の変動を固定するため、保存済み検索ページは再開時に取り直さない。

## 既存DB（今回変更しない）

| 用途 | 識別先 | 今回の扱い |
| --- | --- | --- |
| 稼働中の従来アプリ | Dockerコンテナ `news-weave-db-1`、PostgreSQL DB名`news` | 読み取りのみ。コンテナ停止・スキーマ変更を行わない |
| 別の既存PostgreSQL | Dockerコンテナ `ai-iot-news-db-1` | 接続・変更しない |
| 旧7段階SQLite | `\\TRUENAS\dev\codex\newsWeave\.local\newsweave-seven-stage-20261015.sqlite` | 旧comparisons構造。本実行開始時のarticlesは0件。変更しない |
| 既存取得済みの公式HTML | `\\TRUENAS\dev\codex\newsWeave\.local\extraction-1000-20261013\collection-audit.sqlite` | `mode=ro`で読み取り、今回の検索候補に一致する公式HTMLだけを再利用する |

`.env`の従来用`DATABASE_URL`は新DBの接続先に使用しない。新DBは`--database`または`PIPELINE_DATABASE_URL`で明示する。既存の接続設定ファイルは書き換えていない。認証情報はこの記録やソースZIPに含めない。

旧7段階SQLiteの開始時SHA-256:

```text
d30493bb0ebbe809b37142258f983a36a79517d960e4f102851a902b2ce108dc
```

## 選定結果の参照とその後の再開

読みやすい一覧は`selections.md`、記事ID・URL・本命/予備・選定理由は`selections.json`、実行IDと件数は`run-manifest.json`へ出力する。実モデルの応答ID・返却モデル・トークン数は`api-calls.jsonl`、選定要求・応答の原文は`model-io/`に保存する。

新DBを現行アプリから参照する例:

```powershell
$taskDatabase = 'sqlite:///C:/Users/driot/Documents/Codex/2026-10-15/pr-times-2000-db-db-db/outputs/newsweave-electronics-mobile-2000-20261015.sqlite'
news-weave --database $taskDatabase list
```

後日⑥以降も実行したい場合は、APIキーを実行環境へ設定し、`run-manifest.json`に記録した実行IDを指定する。

```powershell
news-weave --database $taskDatabase resume <run_id>
```

このresumeは実際に生成・検証APIを呼び出す。⑤の保存済み選定は再利用される。この選定スナップショットは保持し、追加依頼の生成・検証は下記の別DBで完了した。

## 実行ソース

`execution-source.zip`に元の現行アプリのコピー、今回の収集・実行スクリプト、およびテストを保存する。実行時は本チャットの作業コピーに適用し、実行後にユーザーのcommit/push依頼でリポジトリへ反映した。`require_domain=False`による今回限定の条件変更と、`process(..., stop_after='select')`およびCLIの`--stop-after select`を追加した。選定応答のスキーマには、判定と組数の対応（本命・予備の両方があれば`TWO_SETS`）を明記した。既定のAI/IoT条件や通常の全段階実行は維持する。

ZIPを展開して`runtime`で依存パッケージをインストールすれば、選定後停止のCLIも利用できる。

```powershell
news-weave --database $taskDatabase resume <run_id> --stop-after select
```

上記のCLI変更は本記録と同じコミットで元リポジトリへ反映した。

収集の実行スクリプトは`collect_stream.py`であり、`acquire.py`は共通の接続先・関数を定義する補助モジュールである。今回の作業ディレクトリ構成（`work`と`outputs`が同じ親にある構成）で使用する。

選定一覧Markdownでは、原資料タイトルに含まれていたNUL制御文字を表示上除去した。DB、選定JSON、モデルへの入力・応答原文は保持している。

## 追加の比較記事生成・検証実行

2026年10月15日の追加依頼により、GPT-6.1 Sol生成・GPT-6 Astra検証を別DB・別実行IDで実行する。[生成・検証用DBの利用方法](generation-sol-astra-20261015/database-guide.md)を参照。上記の選定用DBは保持する。
