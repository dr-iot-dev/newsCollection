# AI/IoT News Collection

公式の一次情報を監査可能な形で収集・編集・公開するためのモジュラーモノリスです。
設計書の Phase 0〜4（基盤・収集・本文抽出・編集レビュー・WordPress連携）を実装しています。

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
代表記事だけがPhase 3の `facts` outboxへ進みます。編集レビュー・公開の手順は以下を参照してください。

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

## Phase 3: facts・AI・内部レビュー API

根拠付きfacts、候補選択、比較データ、ArticlePackage、草稿、独立検証、人間レビューを実装しています。
各成果物は版とハッシュで追跡し、取得した記事の新版・草稿の新版・検証モデルやpolicyの変更後には旧承認を流用できません。

### 記事を読む

APIはこのPCの `http://127.0.0.1:8000`、開発用OpenAPI画面は `/docs` です。
記事本文・facts・草稿は内部情報のため、Bearer認証を必須にしています。
通常の起動では閲覧用アカウントも自動で作成しません。CLIで次のように作成できます。

```console
docker compose run --rm collect ai-iot-news auth create-user --name reader --role viewer
```

表示されたtokenを `/docs` の **Authorize** に入力します。tokenはDBにハッシュだけを保存します。
既存ユーザーのtokenは再表示できません。不要なユーザーは `auth revoke --name reader` で無効化できます。

- `GET /api/v1/items`: ページング、状態・source key・タイトル検索。
- `GET /api/v1/items/{id}`: 抽出本文、公開日時、factと根拠の文字位置、草稿、前版との差分、検証結果。
- `GET /api/v1/items/{id}/candidate-decisions`: 採用・保留・却下とその理由。
- `GET /api/v1/article-packages/{id}`: Writerへ渡す検証済み情報。
- `GET /api/v1/drafts/{id}/verifications`: 独立検証履歴。
- `GET /api/v1/audit-events?item_id={id}`: 操作者と状態遷移。

編集操作には `editor`、レビューには `reviewer` roleが必要です。異なる人にそれぞれのアカウントを発行してください。
同一アカウントによる草稿作成と承認は、既定の4-eyes設定で拒否します。

### 処理を実行する

収集済みの代表記事をschedulerがrulesによるfacts抽出、候補選択、比較パッケージ生成へ進めます。
低品質・権利未確認・重複・プロンプトインジェクション疑いは処理を止めます。
rulesは明示的な企業名・製品名ラベル、仕様、円価格、発売日ラベルのみを抽出する保守的な補助処理です。
必要情報が足りない記事は候補を保留し、製品・企業・日付・比較値を推定しません。

```console
docker compose run --rm collect ai-iot-news editorial run --item ARTICLE_UUID --stage facts --mode rules
docker compose run --rm collect ai-iot-news editorial run --item ARTICLE_UUID --stage facts --mode ai
docker compose run --rm collect ai-iot-news editorial run --item ARTICLE_UUID --stage pipeline --mode ai
```

APIでは `/items/{id}/facts`、`/select`、`/comparison-package`、`/ai-draft`、`/reprocess`、
`/drafts/{id}/verify` をPOSTします。`expected_version`には一覧・詳細で取得した **workflow_version** を指定します。
202とjob_idを返し、schedulerが実行します。`GET /api/v1/jobs/{job_id}` で結果を確認してください。
再送は同じjobを返します。失敗した要求を明示的に再試行する場合は、新しい `request_id` UUIDを指定します。
`POST /items/{id}/drafts` は検証済みWritingOutputから手動の新しい草稿revisionを作ります。

比較は承認済みの既存記事に含まれる検証済みfactsだけを利用します。
`comparison-package` に `previous_item_ids` と `competitor_item_ids` を指定できます。
従来製品は同じ企業かつ発表日が前、競合製品は別企業であることを確認します。
比較資料が足りない場合は調査範囲と「比較不能・追加調査が必要」を保存し、取得モジュールへの検索要求をoutboxへ記録します。
自動検索は登録済み・承認済みソースの収集データと許可された収集経路を使います。任意URLや禁止ページは取得しません。手動で参照記事を指定することもできます。

### 外部 AI の設定

既定値は `AI_PROVIDER=disabled` です。`.env` でプロバイダーを明示し、用途別モデルを設定して再起動してください。

```dotenv
AI_PROVIDER=openai
AI_API_KEY=YOUR_PRIVATE_KEY
AI_MODEL_FACTS=YOUR_FACTS_MODEL
AI_SELECTOR_MODEL=YOUR_SELECTOR_MODEL
AI_WRITER_MODEL=YOUR_WRITER_MODEL
AI_VERIFIER_MODEL=YOUR_DIFFERENT_VERIFIER_MODEL
AI_REQUIRE_DISTINCT_MODELS=true
```

Responses APIの [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) を利用します。
API keyは環境変数だけで渡し、ツール権限を与えず、`store: false`、入力・出力サイズ上限を適用します。
問い合わせ先は文字位置を保持したままマスクします。factsの根拠は元の抽出本文と照合します。
不正なfacts・Writer出力の修復は最大1回です。Verifierのエラー・不正JSONは合格になりません。
モデル・prompt・入力hash・request ID・token数・処理時間を `ai_runs` に記録します。
費用は単価が設定されている場合だけ推計し、未設定では不明として保存します。
外部AIを有効にするとschedulerが待機中の草稿作成・検証メッセージも実行します。

### 承認条件

`POST /api/v1/items/{id}/reviews` には最新の `draft_id`、`expected_version`、decisionと全checklist項目が必要です。
`approve` では最新草稿・最新ArticlePackage・最新policy/modelの独立検証pass、ソース条件、全checklist完了を検証します。
古い版、不完全なchecklist、検証失敗、同一作成者による承認は409で拒否します。
Writerにない数値・固有名詞、比較欠落、条件差、原文の長い一致、個人情報はコードの検査とVerifierの両方で確認します。
人間レビューを省略しません。WordPress送信・公開は以下のPhase 4の明示的な操作で行います。

## Phase 4: WordPress 下書き・公開

WordPress連携は既定で無効です。専用ユーザーのApplication Passwordと既存のカテゴリ・タグIDを
環境変数に設定します。サイトのルートURLを指定してください（サブディレクトリ設置にも対応）。
APIとschedulerには同じ設定を渡します。HTTP、資格情報入りURL、redirect、
private/reserved IPへの接続を拒否し、HTTPSの証明書検証とDNS固定を適用します。

```dotenv
WORDPRESS_ENABLED=true
WORDPRESS_BASE_URL=https://cms.example
WORDPRESS_USERNAME=news-integration
WORDPRESS_APPLICATION_PASSWORD=YOUR_PRIVATE_APPLICATION_PASSWORD
WORDPRESS_CATEGORY_MAP={"iot_platform":12,"edge_ai":15}
WORDPRESS_TAG_MAP={}
```

分類keyや草稿tagに対応する既存IDがなければ送信前に422で停止します。カテゴリ・タグの新規作成、
画像やmediaのアップロードは行いません。MarkdownをHTMLへ変換し、許可タグとHTTPSリンクだけを残し、
ArticlePackageの出典リンクを付けます。送信するのは承認済みの編集原稿です。

DBの追加revisionは `20261001_0004` です。更新を反映する際は
`docker compose up --build -d --wait` でmigrationとAPI/schedulerの更新を行います。
既存publicationには `legacy` を付け、証跡のない投稿を自動で公開しません。

`collect` は `tools` profile のサービスなので、通常の `docker compose up --build` では
更新されません。更新後のCLI実行には `docker compose run --rm --build collect ...` を使うか、
先に `docker compose build collect` を実行してください。古いイメージでは `publisher` が
`invalid role` として拒否されます。

```console
docker compose run --rm --build collect ai-iot-news auth create-user --name publisher --role publisher
```

人間レビューの承認後、次のAPIを順に実行します。各操作では、直前の応答または記事詳細から得た
最新の `workflow_version` を `expected_version` に指定します。
`draft_id` は承認済みの最新草稿IDです。エラー後も記事詳細を再取得して版を確認してください。

| 操作 | API | 権限・追加入力 |
|---|---|---|
| 下書き送信 | `POST /api/v1/items/{id}/wordpress/draft` | editor、expected_version、draft_id |
| 公開承認 | `POST /api/v1/items/{id}/wordpress/publish-approval` | publisher、expected_version、draft_id、publication_id、confirm_publish: true |
| 公開実行 | `POST /api/v1/items/{id}/wordpress/publish` | publisher、expected_version、draft_id、publication_id、publish_approval_id |
| 送信履歴 | `GET /api/v1/items/{id}/publications` | 認証済みユーザー |
| 手動照合 | `POST /api/v1/publications/{publication_id}/reconcile` | editor |

WordPress 送信時は、草稿本文の出典セクションを、記事パッケージの出典 URL から作るリンク付きの1つにまとめます。
草稿本体の出典は人間レビュー用に保持します。

下書きAPIは常に `status: draft` です。公開承認は人間レビューとは別の記録で、
itemの版・review ID・送信payload hash・WordPress上の内容hashに結び付きます。
公開直前にも最新草稿、facts、権利条件、独立検証のpolicy/model、checklist、アカウントの有効性と権限を確認します。
4-eyes有効時は草稿作成者が公開承認することも拒否します。

同じサイト・item・草稿revisionは一つのpublicationに対応し、決定的なslugで照合します。
WordPress上のraw title/content/excerpt、slug、カテゴリ・タグ、status、更新日時が変更されていたら409で停止し、
人手編集を上書きしません。公開リクエストが送るのは既存postの `status: publish` だけです。
WordPressの標準APIには原子的な更新条件がないため、最終GET直後の人手編集との競合を完全に排除するには、
CMS側の排他制御を追加する必要があります。

送信試行はPOSTの前にcommitします。タイムアウトや5xx後はremote IDまたはslug・payloadを照合し、
新しいpostの作成を自動再送しません。投稿が見つかればローカルの送信結果を回復します。
見つからない場合は `WORDPRESS_RECONCILIATION_PENDING` として保留します。
送信前のプロセス停止やslugの手動変更でもこの状態になり得ます。WordPress管理画面と送信履歴を確認し、
未作成が確実な場合にだけ運用担当者が試行記録を回復してください。自動reset APIは提供しません。
公開のタイムアウトは既存postを確認し、承認に対応する公開成功が確認できるまでローカルをPUBLISHEDへ進めません。

schedulerは30分ごとに最大100件をGETで巡回・照合します。下書き作成や公開のPOSTは明示的なAPI操作で実行します。
429/5xxのGETはRetry-Afterを考慮して最大3回、長い待機は次回へ繰り越します。POSTの自動再送は行いません。
認証・失敗ログ・API応答にApplication PasswordやWordPressのエラー本文を含めません。

WordPress mockを使って、作成/公開の送信前後タイムアウト、同時送信、二段階承認、権限失効、
草稿・ソース・model変更、外部編集、HTML安全化、migrationのupgrade/downgradeを検証します。
実サイトのテーマ・プラグインによるHTML変更やAPIの権限設定は、接続先のstagingで確認してください。
認証と投稿APIは[WordPress認証仕様](https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/)と
[Posts API](https://developer.wordpress.org/rest-api/reference/posts/)を参照しています。


## AI 検証失敗の診断と比較記事の確認

AIの応答が検証に失敗した場合は、`ai_runs.validation_errors_json` に固定のエラーコード、
日本語の説明、項目の位置 (`path`)、試行回数 (`attempt`) を保存します。
形式のエラーでは `condition` と数値の制約 `limits` も保存します。
同じ情報を `ai_validation_failed` として構造化ログに出力します。
APIキー、却下した回答本文、例外の生メッセージ、未知の項目名は診断に保存しません。

- `GET /api/v1/jobs/{job_id}` の `ai_runs`: そのジョブが実行したAIの試行と診断。
- `GET /api/v1/items/{item_id}` の `ai_runs`: 記事に関する直近20件の試行と診断。
- `validation_errors: null`: この機能追加前の実行など、診断記録なし。
- `validation_errors: []`: 応答の検証に合格。

DB revision `20261002_0005` を `docker compose up --build -d --wait` で反映します。
過去の失敗した応答は保存していないため、過去の具体的な失敗条件は復元できません。
ジョブの `status: success` は処理完了を意味し、草稿の独立検証の合格は `result.status: pass` で確認します。

記事詳細の `extraction` は収集元の正規化本文です。比較を含む生成草稿は `drafts`、
独立検証の結果は `verifications` に入ります。比較データ作成と草稿生成はPhase 3で実行し、
Phase 4は承認済み草稿をWordPressへ送信・公開します。
`reprocess` または `comparison` のリクエストの `previous_item_ids`、`competitor_item_ids` に
比較対象記事のUUIDを指定します。比較対象にも最新の検証済みfactsが必要です。
同社の従来記事は発表日時が対象より前であること、他社記事は別の企業であることも検証します。
比較対象がない場合は理由を比較パッケージと調査記録に残し、追加調査要求を記録します。原稿には比較不能の欄を表示しません。
比較対象が未指定の場合は、以下の自動比較検索を実行します。


## 自動比較検索と草稿の完成

`POST /api/v1/items/{item_id}/reprocess` は既定で `auto_research: true` です。
記事の事実抽出・選定後、従来製品と競合製品を自動検索し、参照記事の事実を検証して
比較パッケージを作成します。その後、草稿作成と別モデルによる独立検証まで進みます。
`comparison` APIと通常のscheduler経路も同じ検索処理を使います。
人間レビュー、WordPress送信、公開承認は従来どおり明示的に行います。

```json
{
  "expected_version": 6,
  "mode": "ai",
  "auto_research": true
}
```

`expected_version` は記事詳細の最新 `workflow_version` に置き換えてください。
`previous_item_ids` / `competitor_item_ids` の手動指定は優先し、未指定の関係だけを検索します。
`auto_research: false` は手動指定または比較対象がない状態での草稿作成を選ぶ場合に使用します。

検索は登録済みでenabled、利用条件承認が有効なソースに限定します。
同じ企業で公開時刻が対象より前の関連製品を従来製品、異なる企業の関連製品を競合として扱います。
製品クラス・製品名・タイトルのキーワードを使って関連候補を絞り込み、企業・製品の一意な識別と
比較軸は検証済みfactsで確認します。関連性の検索判定はルールによる候補判定であり、
同等性能や優劣を保証しません。条件差や不足は草稿と独立検証で確認します。
登録済みデータで不足する場合は、各ソースの収集間隔・429待機・ページ数上限を守って更新します。
Webは許可ホスト・URLパターン・robots・規約検査を通過した一覧/詳細のみ、
RSSはフィード本文のみ、GitHubは設定されたリリースページ範囲を取得します。
検索エンジン全体や未登録サイトへの検索・巡回は実装対象外です。

`GET /api/v1/items/{item_id}` の `research_requests` に検索結果を表示します。
各要求の `result.selected` は採用記事ID、version、evidence hash、score、
`result.rejected` は不採用理由、`source_checks` はソース更新結果です。
`attempt`、`available_at`、`error.code` で再試行と停止理由を確認できます。
待機中のジョブは `status: waiting_research` / `result.status: research_pending`、
`next_run_at` は次回実行予定です。同じ `job_id` を確認し続けてください。
失敗時は `error_code`、完了時は `result.status` と `draft_id` / `verification_id` を確認します。
`pass` は独立検証合格で、生成草稿は記事詳細の `drafts` に入ります。

候補・事実検証・更新ソース・再試行回数には上限があります。既定値は環境変数で変更できます。

```dotenv
COMPARISON_AUTO_RESEARCH=true
RESEARCH_REFRESH_SOURCES=true
RESEARCH_MAX_CANDIDATES=100
RESEARCH_MAX_FACT_CHECKS=6
RESEARCH_MAX_SOURCES_PER_ATTEMPT=6
RESEARCH_MAX_ATTEMPTS=3
RESEARCH_RETRY_SECONDS=60
```

参照記事の事実が足りない場合はrulesを試し、必要なら設定済みのfacts用AIを使用します。
これにはAPI利用料金が発生します。失敗した同じ参照記事/versionは要求内で繰り返しAIに渡しません。
検索範囲内で根拠が見つからない場合や上限到達時は、比較不能の理由を調査記録に残して草稿を作成します。
取得失敗の再試行中は草稿作成を待機します。内容の更新・権利の失効・人間の変更を検知した
古い要求や待機ジョブは処理を停止し、承認済み記事や手動草稿を検索ワーカーが上書きしません。

DB revision `20261002_0006` を含む更新です。
`docker compose up --build -d --wait` で反映し、CLI利用時は `docker compose build collect` も実行します。


AI事実抽出は本文と完全一致する根拠から文字位置を確定します。文脈付きの日付は、
値と精度が一致する本文内の日付表記だけに絞ります。年の補完や精度の変更はしません。
候補ごとにすべての事実検証を実施し、未検証の候補を除外した場合は
`ai_runs.validation_status: valid_with_rejections` と具体的な `validation_errors`、
EvidencePackageの `uncertainties` に記録します。writerには合格したfactsのみ渡します。
候補がすべて不合格の場合は従来どおり失敗します。会社・製品・発表事実が不足する場合は
選定を保留し、草稿の独立検証と人間レビューも従来どおり必須です。


独立検証ポリシー `verification-v6` では、確認済みの比較対象が本文に自然に組み込まれ、
同社の従来製品と他社の製品の区別を文章で明示することを必須とします。比較対象がない側は本文から省きます。補助適用後の価格は、価格を記載する段落で
補助条件も示す必要があります。旧ポリシーの合格結果は公開前に再検証してください。

宣伝・効果の断定を防ぐ検証ポリシー `verification-v3` では、該当表現の段落ごとに発表者への帰属を要求します。旧ポリシーの合格は再検証が必要です。


### トピックと比較対象の選定・比較結果の記録

従来の `topic` はタイトル文字列でした。現在は `topic_profile` に記事本文・タイトルから分類した用途、利用環境、機能、利用者、記事の主題を保持します。分類方法は `source_keyword_rules` です。設定済み語彙に合わない観点は `unknown_dimensions` に残し、推測で補完しません。分類規則は `app/modules/research/topics.py` の `TAXONOMY` に集約しています。変更時は `POLICY_VERSION` を更新してください。分類根拠は元タイトル／正規化本文の `field`・`start`・`end`・`quote`、原文版・抽出ハッシュ・分類規則版とともに保存されます。

選定ポリシー `research-v3` は用途・利用環境・機能トピックのすべての一致を必須とします。「介護・見守り」や `hardware_spec` の一致だけでは選びません。同社旧製品の会社／公開日時、他社製品の会社相違、両側で確認できる具体的な比較軸も検査します。利用者と記事の主題（製品発表、共同検証、自治体補助登録など）の差も記録します。順位点は必須トピック一致数×100＋両側で確認できる特徴軸数×10＋利用者・主題の一致数です。探索件数・事実抽出数は従来どおり上限があります。

比較軸は検知方式、観測する状態、通信方式、通知手段、カメラ使用、メモリー、互換性、ソフトウェア要件、価格条件、標準、ライセンスです。特徴値には検証済み `fact_ids`／`evidence_ids` を付けます。結果は `common`（共通）、`different`（相違）、`partial_overlap`（一部共通）、`unknown`（未記載）、`not_comparable`（条件不一致・未確認）です。未記載は非対応を意味せず、価格の地域・補助条件が揃わなければ優劣を比較しません。

記事詳細 `GET /api/v1/items/{item_id}` の `topic_profile`、`comparison_analyses`、`article_package.comparison.analysis`、`research_requests[].result.candidate_assessments` で確認できます。採用候補と不採用候補のチェック項目・理由コード・特徴比較を保存します。`GET /api/v1/items/{item_id}/comparison-analysis` は分析履歴を返します。

編集者は `POST /api/v1/items/{item_id}/comparison-analysis` に最新の `expected_version` と `competitor_item_ids`／`previous_item_ids` を渡すと、指定候補について分析を保存できます。この操作は記事収集・草稿生成・外部AI呼び出しを行わず、草稿やワークフロー状態を変更しません。同じ入力は同じ分析IDを返し、原文や規則が変わると新しい記録を追加します。保存先は追記型の `module_messages`（`article_topic`／`comparison_audit`）で、既存履歴を上書きしません。

`writing-v4` は分析を含む原稿パッケージを使用し、`verification-v6` は比較対象の適合性を確認します。旧ポリシーの合格は人間承認・WordPress送信前に再検証が必要です。Caremoの介護施設でのバイタル・転倒検知の共同検証と、ここわの在宅生活活動見守りの自治体補助登録は、利用環境と機能が異なるため新しい選定規則では除外されます。


比較は製品紹介・特徴の説明と同じ本文の流れに組み込み、「他製品との比較」等の独立した見出しを表示しません。確認できた従来製品・他社製品だけを扱い、その区別を初出の文章で明示します。比較不能の理由は原稿パッケージ・調査履歴に保存します。生成AIは比較を `paragraphs` に組み込み、両製品のfact_idを各段落に付けます。互換用の `previous_comparison` と `competitor_comparison` は生成AIでは空文字です。従来の手動入力から受けた比較文は、見出しを付けずに本文へ結合します。

タイトルは60文字以内（生成時は30〜45文字を目安）で、製品・サービスの種類と原稿の観点を伝えます。比較対象名の列挙は不要です。独立検証の `title_clarity` でも内容との整合性と分かりやすさを確認します。

独立検証の応答スキーマは対象稿・パッケージ・ポリシー・必須項目を固定し、根拠の `fact_ids` をパッケージ内の検証済みIDに限定します。合否と説明は独立検証AIが判断します。契約不一致は項目・配列位置を含む `ai_runs.validation_errors.path` に記録し、不正な応答を合格扱いしません。

比較対象の紹介・説明は原稿全体で原則一度にまとめます。レンダラーは定型の紹介文を自動挿入せず、同社従来製品・他社製品の区別は初出の自然な文章で示します。その後は共通点・相違点の説明や曖昧さの解消に必要な参照だけにします。独立検証の `editorial_conciseness` で不要な再紹介・同じ説明の繰り返しを検査します。タイトル末尾の「を比較」は生成時・手動入力時・独立検証時に禁止します。
