# AI/IoT News Collection

公式の一次情報を監査可能な形で収集・編集・公開するためのモジュラーモノリスです。
設計書の Phase 0（基盤・契約・DB・設定）と Phase 1（RSS/Atom・GitHub Releases収集）を実装しています。

## ローカル起動

1. 必要なら `.env.example` を `.env` にコピーし、`POSTGRES_PASSWORD` を変更します。
2. `docker compose up --build -d --wait` を実行します。
3. `http://localhost:8000/health/live` と `/health/ready` を確認します。

`migrate` サービスがDBを更新してからAPIとschedulerが起動します。APIとschedulerは
非root・read-only filesystemで動作します。APIは `frontend` と内部の `backend` に接続し、
`127.0.0.1:8000` にだけ公開します。DBとmigrateは `backend` のみに接続します。
schedulerと手動収集用 `collect` は、取得のため `backend` と `collection` に接続します。

## Phase 1: ソース登録と収集

`config/sources.example.yaml` は設定の例です。`vendor.example` は取得できません。
実運用の設定に置き換え、法務承認・確認日・承認者と許可ホストを設定してからDBへ同期してください。
DBに同期されていない設定はschedulerから読み込まれません。
以下ではイメージに同梱される例を使っています。独自設定は `collect` にread-onlyでマウントできます。

```console
docker compose run --rm collect ai-iot-news sources validate config/sources.example.yaml
docker compose run --rm collect ai-iot-news sources sync --dry-run config/sources.example.yaml
docker compose run --rm collect ai-iot-news sources sync config/sources.example.yaml
docker compose run --rm collect ai-iot-news collect run --source github-esphome --dry-run --force
docker compose run --rm collect ai-iot-news collect run --source github-esphome --force
```

収集のdry-runは実際にGETして追加・更新件数を表示します。DBのsource、item、version、snapshot、
cursor、job、audit、outboxは変更しません。`--force` は通常の収集間隔を無視しますが、
サーバーのrate limitによる待機は維持します。ソースを指定しなければ全登録ソースを順に確認します。
schedulerは60秒ごとに有効・承認済み・実行予定時刻に達したRSS/GitHubソースを確認します。
未承認・無効・確認から180日を過ぎたソースはHTTPリクエスト前に拒否します。
旧版で同期したソースは法務証跡とdefaultsを補うため、設定を再同期してください。

- RSS 2.0/Atom: GUID/entry ID、正規化link、安定したhashの順に識別します。HTMLはプレーンテキスト化し、script等は破棄します。
- GitHub: release IDで識別し、draft/prereleaseは既定で除外します。bodyはMarkdownのまま保存し、assetsは取得しません。
- title、本文、公開日時、releaseのupdated_at等が変わると同じitemのversionが増えます。同じ入力の再取得では増えません。
- ETag/Last-Modifiedはページごとに保持します。GitHubは先頭ページが304でも後続ページを確認します。
- JSON/XML解析失敗、禁止URL、途中ページの失敗では記事・版・cursorを変更せず、取得済みsnapshotと失敗jobを残します。
- 原文snapshotは既定365日の保持期限とSHA-256を記録します。新版から抽出用 `AcquisitionResultV1` をoutboxへ送ります。
- HTTPS、許可ホスト、公開IP検査、DNS固定、TLS証明書検証、各redirectの再検査、展開後サイズ上限を適用します。
- 同一プロセスではホスト単位の待機とソースの逐次処理を行います。同一ソースの同時収集はPostgreSQLの行ロックで直列化します。
- 429/503等は最大3回再試行し、長いRetry-After/GitHub resetは次回実行へ繰り越します。Cookieは保持せず、安全なレスポンスヘッダーだけ保存します。

RSSの `allowed_hosts` を省略するとフィードURLのホストだけを許可します。別ドメインのentryやredirectを
許可する場合は、フィードのホストを含めて明示します。ソースごとに `min_delay_seconds`（既定3秒）、
GitHubには `max_pages_per_run`（既定10、1ページ100件）を指定できます。ページ上限到達時は
部分取得を成功扱いにせずcursorを更新しません。展開後の累積取得サイズにも `max_response_bytes` を適用します。
GitHubの認証は任意の `GITHUB_TOKEN` 環境変数から読みます。トークンをYAMLやURLに入れないでください。
GitHub APIの仕様は[Releases API](https://docs.github.com/en/rest/releases/releases)と
[利用上の推奨事項](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)に合わせています。

Web巡回、robotsゲート、リンク先本文の抽出、重複候補判定はPhase 2で実装します。
Phase 1はフィードとリリースAPIの取得に限定しています。

## 開発とテスト

```console
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
ruff check .
mypy app
pytest
```

Dockerでlint、型検査、全テスト、PostgreSQL統合試験を一括実行できます。

```console
docker compose --profile test build test
docker compose --profile test run --rm test
```

統合試験はDB内に一意なテスト用schemaを作り、終了時にそのschemaだけを削除します。
通常のsources/itemsには書き込みません。ローカルpytestでは `TEST_DATABASE_URL` が未設定なら
PostgreSQL試験をskipし、SQLiteとHTTP fixtureの試験を実行します。
同一入力3回、更新による版追加、同時取得、304/429/503、途中失敗、dry-run、SSRF、DNS rebinding、
圧縮サイズ上限、法務ゲートを検証します。

## 実装境界

- モジュール間の値は `app/contracts` の版付きDTOで渡します。
- 他モジュールのrepositoryや内部domainを直接importしません。
- Writer/Verifier向けDTOに原文全文、Cookie、資格情報を含めません。
- DB変更はAlembic経由で行います。Phase 1はPhase 0の既存テーブルを使用します。

詳細は [ai_iot_news_collection_system_design.md](ai_iot_news_collection_system_design.md) を参照してください。