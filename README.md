# AI/IoT News Collection

公式の一次情報を監査可能な形で収集・編集・公開するためのモジュラーモノリスです。
設計書の Phase 0（基盤）、Phase 1（RSS/Atom・GitHub Releases収集）、Phase 2（Web収集・本文抽出・重複判定）を実装しています。

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
schedulerは60秒ごとに有効・承認済み・実行予定時刻に達したRSS/GitHub/Webソースを確認します。
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

## Phase 2: Web収集・本文抽出・重複判定

Webソースでは `collection_basis: permitted_web`、承認者、`terms_reviewed_at` と
`robots_reviewed_at` が必要です。`list_url`、利用規約URL、記事URLは同じHTTPS originに置き、
`allowed_hosts` と記事の `allow_url_patterns`、`deny_url_patterns` を指定します。
一覧ページのpaginationは `selectors.next_page` で指定でき、同じpathのqueryによるページ送りに対応します。
別pathへのページ送りは取得前に拒否します。JavaScript・ログイン・画像等の追加リソースは取得しません。

- 各実行で robots.txt を先に取得し、利用規約・一覧・詳細・redirect先の許可をGET前に検査します。
- robotsの照合は [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html) のgroup結合、最長一致、Allow優先、wildcard、末尾記号、percent encodingに対応します。安全側の運用として404・5xx・timeout・空/不正robotsでは本文を取得しません。
- robotsの `Crawl-delay`（最大60秒）と設定の待機時間の大きい方を使います。IP literal、private/reserved IP、userinfo URLを拒否し、redirectでもDNS検証・固定を行います。
- robotsと利用規約のhash・判定・確認日時を保存します。初回取得はYAMLの承認に対応するbaselineとして記録します。以降に変更を検知すると `pending` に戻し、本文GETを停止します。
- 再確認後は両方の確認日時を変更検知日時より新しくして同期してください。同じ承認記録の再同期や `--force` では解除できません。利用規約の比較はscript/navigation等を除いたテキストで行います。
- Webの `max_pages_per_run`（既定20、2〜100）は一覧・詳細・redirect・retryの実リクエスト数を制限します。robots/規約の2つの制御文書は別枠です。未処理URLをcursorに残して次回再開します。サイズ超過や途中失敗では記事・取得cursorの変更を取り消します。法務判定と取得済みsnapshotは保持します。
- 一覧が304でも保存したリンクを使って詳細を確認します。同じ記事の更新はversionとして保存します。RSSのリンク先は自動巡回せず、Webソースとして明示した範囲を収集します。

取得outboxを `extraction` → `deduplication` の順に処理します。手動収集は収集のcommit後に処理し、
schedulerも定期的に未処理メッセージを進めます。各段階を別モジュール・版付きDTOで分離しています。
過去の未処理データや残ったbatchを処理するには次のコマンドを使います。

```console
docker compose run --rm collect ai-iot-news pipeline run --limit 100
```

本文抽出は [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) を使い、
サイト指定selector、JSON-LD Article/NewsArticle、OpenGraph等のmetadata、article/mainと静的DOMの順に補完します。
script/style/noscript/nav/footer/フォーム/非表示要素/cookie bannerを除去し、Unicode NFC・改行・空白を正規化します。
見出しとリストの改行は保持します。公開日時と更新日時は分け、日付のみの情報には時刻を補いません。
言語の由来とconfidenceも保存します（HTML metadata、設定、限定的な日本語文字種判定）。

品質scoreはtitle、本文長、公開日、構造化titleの一致、本文比率、boilerplate、指定selectorの一致で算出します。
長さだけで通過させず、短い本文・構造を特定できないページはreview対象とします。
0.6未満は `REVIEW_PENDING` にして、Phase 3向けメッセージを作成しません。
抽出結果とhashは `extraction_results` に記事のversionごとに保存します。取得時のhashは上書きしません。

重複判定はtracking query/fragmentを除いたURL、正規化本文hash、64-bit SimHash、title、メーカー/型番の
明示的なanchor、公開日、同じhostかを使います。意味のあるqueryと末尾slashは保持します。
各比較のscore・理由・相手のversionを `duplicate_decisions` に保存します。
完全一致、またはscore 0.92以上でtitle・本文・identity・日付・数値仕様・技術語の条件も一致した場合に
代表記事へ関連付けます。0.80以上の曖昧な候補はレビュー待ちとし、記事は削除しません。
代表記事が更新された場合は以前の関連付けを解除してレビュー待ちにします。
代表記事だけがPhase 3の `facts` outboxへ進みます。AIによる事実抽出・執筆・公開は次フェーズです。

ラベル付きfixtureは56組（重複24組、別記事32組）です。完全一致、tracking、句読点の違いに加え、
メーカー・型番・数値仕様・公開日の違いを含み、自動判定のprecision 99%以上をテストします。
fixture上の結果であり、実サイト全体の精度保証ではありません。

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
圧縮サイズ上限、法務ゲート、robots禁止URLのGETゼロ、文書変更、抽出品質、重複精度、
既存DB更新と新規DB作成のmigrationを検証します。

## 実装境界

- モジュール間の値は `app/contracts` の版付きDTOで渡します。
- 他モジュールのrepositoryや内部domainを直接importしません。
- Writer/Verifier向けDTOに原文全文、Cookie、資格情報を含めません。
- DB変更はAlembic経由で行います。Phase 2は `20260930_0002` で抽出・重複判定テーブルを追加します。
- 初期migrationのモデルを固定し、新規作成・既存DB更新・downgrade/re-upgradeで同じschemaになることを検証します。

詳細は [ai_iot_news_collection_system_design.md](ai_iot_news_collection_system_design.md) を参照してください。

## 指定された収集先（2026-10-01）

実運用設定は `config/sources.yaml` に保存しています。PR TIMESのIoT・電子工作を公開情報収集用に
登録し、確認したrobots/規約のURL・確認日・ユーザー指定の記録を保存しています。
1ソースあたり2時間間隔、5秒以上の待機、1回最大6ページ（一覧＋詳細5件）です。
記事本文と公開日時は実HTMLの安定したIDとJSON-LDから抽出します。
時差情報のないPR TIMESの日時には `timezone_hint: Asia/Tokyo` を明示し、その由来も抽出結果に残します。
一覧の「もっと見る」はJavaScript処理のため実行せず、表示される記事の範囲を収集します。
写真やログイン限定情報を取得せず、自動公開は行いません。転載・商用利用の許諾は別途確認が必要です。
[利用規約](https://prtimes.jp/main/html/kiyaku)と[robots.txt](https://prtimes.jp/robots.txt)を参照してください。

日経のトピック24032506も設定に登録していますが、確認ブラウザがrobots.txtで拒否されたため
`enabled: false`、`legal.status: pending` です。NewsCollectionBot向けのルールと記事抽出selectorは
未検証です。取得権限と許諾のある経路を確認した後に有効化してください。

```console
docker compose run --rm collect ai-iot-news sources validate config/sources.yaml
docker compose run --rm collect ai-iot-news sources sync config/sources.yaml
docker compose run --rm collect ai-iot-news collect run --source prtimes-iot --force
docker compose run --rm collect ai-iot-news collect run --source prtimes-electronics --force
```
