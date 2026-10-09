# 環境構築・モデル変更・WordPress運用手順

基準日: 2026-10-07（日本時間）。[記事生成の要求仕様](article-generation-requirements.md) を満たす現行構成を再現するための手順である。資格情報は記載しない。既存サイトの変更や記事の公開を、この手順の文書化だけで実施したものとは扱わない。

## 1. 現行構成

| 項目 | 現行値 |
| --- | --- |
| プロジェクト | `\\truenas\dev\codex\newsCollection` |
| 秘密情報を置くファイル | `\\truenas\dev\codex\newsCollection\.env`（Git対象外） |
| 内部API | `http://127.0.0.1:8000`、OpenAPI画面 `/docs` |
| DB | ComposeのPostgreSQL、volume `postgres-data` |
| WordPress | `https://airlabs.jp` |
| 投稿用ユーザー / 表示名 | `news-weaver`（ID 3） / News Weaver（2026-10-09切り替え済み） |
| 投稿タイプ内部名 / REST名 | `news_weave` / `news-weave`（2026-10-09移行済み） |
| 個別記事 | `/collected-news/{slug}/` |
| 一覧固定ページ | 「ニュースを編む」（2026-10-09反映済み）、page ID 63、`https://airlabs.jp/news/` |
| 稼働サービス | `db`, `migrate`, `api`, `scheduler` |
| 補助サービス | `collect`（tools profile）、`test`（test profile） |

`migrate` の正常終了後にAPIとschedulerが起動する。APIはlocalhostだけに公開される。WordPressから内部APIを呼ぶ必要はない。APIとschedulerがWordPressのHTTPS REST APIへ下書きを送る。

## 2. 必要な環境と初回起動

DockerとDocker Composeを利用でき、コンテナーから登録ソース、AI API、WordPressへ接続できる環境を用意する。ローカルPythonで開発する場合の要求は `pyproject.toml` のPython 3.13以上・3.15未満である。

PowerShellで共有フォルダーから実行する例:

```powershell
$projectRoot = '\\truenas\dev\codex\newsCollection'
Set-Location -LiteralPath $projectRoot
# 初回のみ。.envが存在するときはコピーして上書きしない。
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
```

新しい設置場所では `projectRoot` をチェックアウト先へ置き換える。`.env` をエディターで開いて設定する。APIキー等をターミナル出力・画面共有・Gitへ載せない。

`.env.example` はAIとWordPressが無効な初期値であり、コピーだけでは現行の生成は動かない。以下は現在の既定構成を再現する設定例である。秘密値は自分の値に置き換える。

```dotenv
POSTGRES_PASSWORD=REPLACE_WITH_PRIVATE_DATABASE_PASSWORD
AI_PROVIDER=openai
AI_API_KEY=REPLACE_WITH_PRIVATE_AI_API_KEY
AI_MODEL_FACTS=gpt-4.1-mini
AI_SELECTOR_MODEL=
AI_WRITER_MODEL=gpt-4.1-mini
AI_VERIFIER_MODEL=gpt-4.1
AI_REQUIRE_DISTINCT_MODELS=true
AI_MAX_INPUT_CHARS=50000
AI_MAX_OUTPUT_TOKENS=4000

COMPARISON_MIN_SOURCES=3
COMPARISON_AUTO_RESEARCH=true
RESEARCH_REFRESH_SOURCES=true
RESEARCH_MAX_CANDIDATES=100
RESEARCH_MAX_FACT_CHECKS=6
RESEARCH_MAX_SOURCES_PER_ATTEMPT=6
RESEARCH_MAX_ATTEMPTS=3
RESEARCH_RETRY_SECONDS=60
REVIEW_REQUIRED=false
REVIEW_REQUIRE_FOUR_EYES=true

FEATURED_IMAGES_ENABLED=true
AI_IMAGE_MODEL=gpt-image-1.5
AI_IMAGE_QUALITY=medium
AI_IMAGE_SIZE=1536x1024

WORDPRESS_ENABLED=true
WORDPRESS_BASE_URL=https://airlabs.jp
WORDPRESS_POST_TYPE=news_weave
WORDPRESS_REST_BASE=news-weave
WORDPRESS_USERNAME=REPLACE_WITH_INTEGRATION_USERNAME
WORDPRESS_APPLICATION_PASSWORD=REPLACE_WITH_PRIVATE_APPLICATION_PASSWORD
WORDPRESS_CATEGORY_MAP={"generative_ai":2,"edge_ai":3,"iot_platform":4,"security":5,"standards":6}
WORDPRESS_TAG_MAP={}
```

上のカテゴリIDはairlabs.jp用であり、新しいサイトでは必ず読み替える。モデルは現在の運用値である。直近の記事72・81と同じ執筆設定を使う場合は `AI_WRITER_MODEL=gpt-5.2` とするが、指定モデルを利用できるか、現行アダプターに適合するかを各実行環境で確認する。

Composeは `POSTGRES_PASSWORD` からコンテナーのDB接続URLを組み立てる。ホストでPythonを直接実行する場合の `DATABASE_URL` は接続先に合わせて別途設定する。稼働済みDBのパスワードを `.env` で変えるだけではDBユーザーのパスワードは変更されない。

WordPressを設定する前に内部生成だけ確認する場合は、`WORDPRESS_ENABLED=false` として起動し、接続準備ができてから有効化する。

```powershell
docker compose --project-directory $projectRoot up --build -d --wait
docker compose --project-directory $projectRoot build collect
docker compose --project-directory $projectRoot ps
Invoke-RestMethod 'http://127.0.0.1:8000/health/live'
Invoke-RestMethod 'http://127.0.0.1:8000/health/ready'
```

APIとschedulerは同じ設定を使う。`restart` だけでは変更後の環境変数を読み直さない。変更後は `up -d --force-recreate api scheduler`、コード変更時は `up --build -d --wait` で再作成する。`collect` は通常のupの対象外なので、コード変更後に別途buildする。

## 3. 収集ソースの準備

1. `config/sources.yaml` を確認する。PR TIMESのIoT・電子工作が登録され、日経トピックは未確認のため無効・pendingである。
2. 自分の運用範囲について利用条件、robots、許可ホスト、URL範囲、取得間隔、本文selectorを確認する。承認日・承認者は実際の確認結果で更新する。既存設定の承認記録を、別環境の新しい承認として流用しない。
3. 検証・dry-run同期で内容を確認してから、DBへ同期する。schedulerはDBへ同期した設定を使う。

```powershell
docker compose --project-directory $projectRoot run --rm collect news-weave sources validate config/sources.yaml
docker compose --project-directory $projectRoot run --rm collect news-weave sources sync --dry-run config/sources.yaml
docker compose --project-directory $projectRoot run --rm collect news-weave sources sync config/sources.yaml
docker compose --project-directory $projectRoot run --rm collect news-weave collect run --source prtimes-iot --dry-run --force
docker compose --project-directory $projectRoot run --rm collect news-weave collect run --source prtimes-iot --force
docker compose --project-directory $projectRoot run --rm collect news-weave collect run --source prtimes-electronics --force
```

収集のdry-runでも実際のGETは行う。`--force` は通常の収集予定を無視するが、rate limit、robots、権利条件は無視しない。PR TIMESの設定は2時間間隔、5秒以上の待機、1回6ページ上限である。承認から180日経過や利用条件・robotsの変更を検知した場合は再確認する。

Webの画像、ログイン領域、禁止URLを取得しない。登録外の任意URLを自動検索する仕組みはない。特定の出典URL群から作成する場合も承認済みの取得経路とDBのfactsを準備する必要があり、URL一覧を入力するだけの汎用記事作成CLIは未提供である。

## 4. WordPressの投稿タイプ

2026-10-09に名称をNews Weaveへ変更した。以下は新規導入の名前である。
airlabs.jpも2026-10-09に `news_weave / news-weave` へ移行済みである。
既存の `/collected-news/` URLはサイト側の移行設定で維持している。
旧投稿タイプから記事と送信履歴を移す場合は [名称変更手順](rename-to-news-weave.md) を使う。
現行サイトの表示名・固定ページ本文は、リポジトリの更新だけでは変更されない。

リポジトリの `wordpress/news-weave/news-weave.php` を使う。新規導入では次のいずれかで配置する。

- `wordpress/news-weave` フォルダーをサーバーの `wp-content/plugins/` へコピーする。
- PowerShellで配布用ZIPを作り、管理画面のプラグイン追加画面からアップロードする。

```powershell
New-Item -ItemType Directory -Path (Join-Path $projectRoot '.local') -Force | Out-Null
Compress-Archive -Path (Join-Path $projectRoot 'wordpress\news-weave') `
    -DestinationPath (Join-Path $projectRoot '.local\news-weave.zip') -Force
```

管理画面で **News Weave** を有効化する。プラグインは以下を登録する。

| 設定 | 値 |
| --- | --- |
| 内部名 | `news_weave` |
| 管理画面表示 | ニュースを編む |
| REST | `show_in_rest=true`, `rest_base=news-weave` |
| 閲覧 | `public=true`、個別URLは `news-weave` |
| 対応要素 | title/editor/excerpt/thumbnail/author/revisions |
| taxonomy | 標準 `category` / `post_tag` |
| 専用アーカイブ | `has_archive=false`（一覧は固定ページで作る） |

`https://サイト/wp-json/wp/v2/news-weave` がJSONを返すことを確認する。未公開記事しかなければ匿名アクセスで空配列になる。個別ページが404なら「設定 → パーマリンク」を保存し、rewriteを更新する。

既存の別投稿タイプを使う場合は、対応要素・REST・標準taxonomyを揃え、`.env` の内部名とREST名を変更する。REST名にはスラッシュのない1つの名前を指定する。独自taxonomyのみの構成は現行payloadと互換ではない。[WordPress公式のカスタム投稿タイプREST対応](https://developer.wordpress.org/rest-api/extending-the-rest-api/adding-rest-api-support-for-custom-content-types/)も参照する。

## 5. 専用ユーザーとApplication Password

airlabs.jpでは2026-10-09に新しい編集者ユーザー `news-weaver`（ID 3）へ送信設定を切り替えた。ニックネーム・表示名は `News Weaver` である。新アカウントによる認証と下書き送信を確認済み。既存7記事の投稿者ID 2は変更していない。APIとschedulerは新設定で再作成済みだが、もともとの停止状態を維持している。

1. WordPressに連携専用ユーザーを用意する。このプラグインは標準投稿の権限を使う。下書きの作成・編集、画像のアップロード、必要なら公開を行える権限を割り当てる。所有者や権限に応じた既存記事の読み取りも確認する。
2. 「ユーザー → プロフィール」または対象ユーザーの編集画面で、News Weave用の **アプリケーションパスワード** を発行する。通常ログインのパスワードと区別する。
3. 専用ユーザー名とApplication Passwordを `.env` の2項目へ保存する。ユーザー名は秘密文書に写す必要はなく、パスワードはGitへ含めない。
4. HTTPS経由のREST認証が動くことを確認する。401ならパスワード・ユーザー名・認証ヘッダー、403なら権限やセキュリティプラグインの制限を確認する。

Application PasswordによるHTTPSのBasic認証は [WordPress公式認証仕様](https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/) に従う。プロキシやサーバーがAuthorizationヘッダーを落とさないようにする。エラー診断で秘密値をログに表示しない。

## 6. カテゴリ・タグの対応

WordPressでカテゴリを作成し、各IDを管理画面または `/wp-json/wp/v2/categories` で確認する。現在のサイトでは次の対応である。

| 内部key | WordPress ID |
| --- | --- |
| `generative_ai` | 2 |
| `edge_ai` | 3 |
| `iot_platform` | 4 |
| `security` | 5 |
| `standards` | 6 |

IDを `WORDPRESS_CATEGORY_MAP` のJSON objectに設定する。タグを使用する場合はWordPress側で先に作成し、`WORDPRESS_TAG_MAP` へ対応IDを設定する。未対応keyがあると送信前に停止し、システムが勝手にカテゴリ・タグを作成することはない。

`WORDPRESS_BASE_URL` はWordPressの設置URLであり、`/wp-json/wp/v2/news-weave` などのRESTパスを含めない。サブディレクトリ設置なら設置先まで含める。現行の接続はHTTPS・公開DNS・証明書検証を必要とし、localhostやprivate IP、redirect先への接続は拒否する。

## 7. 固定ページとフロントページのリンク

1. 固定ページ「ニュースを編む」を作成し、スラッグを `news` とする。既存の旧名「収集ニュース」のページ63を更新する場合は新規ページを重複作成しない。
2. 互換モードでは原稿内の `"postType":"news_weave"` を `"postType":"nc_news"` に変更する。ブロックエディターのコードエディターで `wordpress/news-weave-page.html` の内容を貼り付け、ビジュアル表示で確認する。説明文は一般のカスタムHTMLブロック内へ丸ごと貼るのではなく、ブロック原稿として貼り付ける。
3. 冒頭に作成方法、比較記事・比較表であること、資料番号、著作権・正確性・個人情報への配慮を表示する。
4. 後半のクエリーループは `postType=news_weave`（互換モードなら `nc_news`）、`inherit=false`、新しい順、6件/ページである。アイキャッチ、リンク付きタイトル、日付、抜粋、「記事を読む」、ページ送りを表示する。
5. 固定ページのみ公開する。ニュースを編むの下書きは一般向け一覧に出ず、個別記事を公開した後で自動表示される。WordPress標準の公開記事抽出を使い、認証付き下書き一覧を公開ページへ埋め込まない。
6. 本文も一覧ページ内で表示したい場合は、投稿テンプレートに「投稿コンテンツ」ブロックを追加する。現行の一覧原稿は抜粋と個別記事へのリンクである。

クエリーループの操作は [WordPress公式ドキュメント](https://wordpress.org/documentation/article/query-loop-block/) を参照する。テーマの機能に応じて、アイキャッチの表示やスマートフォンの表の横スクロールをプレビューで確認する。

フロントページにリンクを表示するには、固定フロントページを編集して「ニュースを編むを見る」のボタンやリンクを `/news/` へ追加する。サイト全体のナビゲーションへ追加する場合、ブロックテーマはサイトエディターのナビゲーション、対応する従来テーマはメニュー設定で固定ページを選ぶ。実際に使うテーマでプレビューし、保存する。この文書化の作業ではフロントページへのリンク配置は変更していない。

## 8. 記事を1件生成し下書きで確認する

APIで操作する方法を基本とする。自動schedulerが動いているため、収集対象によっては複数の待機記事も処理される。「新しい記事1件の試験」には対象itemを指定し、必要なら隔離した試験環境を使う。

初回のみ、内部APIのeditorアカウントを作る。トークンは一度だけ表示されるため安全に保存する。既存アカウントがあれば再発行を目的に重複作成しない。

```powershell
docker compose --project-directory $projectRoot run --rm --build collect news-weave auth create-user --name editor --role editor
```

`http://127.0.0.1:8000/docs` のAuthorizeにBearer tokenを入力する。WordPressのApplication Passwordとは別の認証である。

1. `GET /api/v1/items` で対象itemを選び、`GET /api/v1/items/{item_id}` で最新の `workflow_version` と状態を取得する。
2. `POST /api/v1/items/{item_id}/reprocess` に次のJSONを送る。`expected_version` は実際の値に置き換える。

```json
{
  "expected_version": 6,
  "mode": "ai",
  "auto_research": true
}
```

3. 202応答の `job_id` を使い、`GET /api/v1/jobs/{job_id}` を確認する。`waiting_research` / `research_pending` なら同じjobの調査待ちである。`job.status=success` は処理終了を意味し、独立検証の合格は `result.status=pass` を確認する。
4. `GET /api/v1/items/{item_id}` のdrafts、verifications、research_requests、ai_runsで、本文、比較表、出典、検証結果と診断を確認する。
5. 最低3資料と別モデル検証の合格後、現行の `REVIEW_REQUIRED=false` ではschedulerがWordPressへ下書き送信する。送信履歴は `GET /api/v1/items/{item_id}/publications` で確認する。
6. WordPressの「ニュースを編む」で、statusが下書き、出典番号と比較表、末尾の使用モデル、アイキャッチを確認する。画像は別ジョブで添付されるため、本文保存より後になる場合がある。

手動で比較対象を指定する場合は、reprocessに `previous_item_ids` / `competitor_item_ids` の配列を追加する。手動だけで進めるなら `auto_research=false` とする。参照記事にも最新の検証済みfactsが必要で、最低資料数と適合条件は変わらない。

CLIを使う場合の補助コマンド:

```powershell
docker compose --project-directory $projectRoot run --rm collect news-weave editorial run --item ARTICLE_UUID --stage pipeline --mode ai
```

CLIの `expected_version` は内部で1を使うため、最新版を指定する操作や比較対象の指定はAPIを基本とする。CLIのpipelineも待機や保留を返し得る。検証合格とWordPressへの送信確認を省略しない。

## 9. 公開と人間レビュー

下書きの自動送信と公開を区別する。現在は人間レビュー前に下書き送信できるが、システム経由の公開は人間レビューと明示的な公開承認が必要である。`REVIEW_REQUIRED=true` なら下書き送信前にも人間レビューを必須にできる。

reviewerとpublisherの内部APIアカウントを必要な担当者に発行する。4-eyesを有効にしている場合、草稿作成者と承認者を分ける。

| 順序 | API | 主な条件 |
| --- | --- | --- |
| 1 | `POST /api/v1/items/{id}/reviews` | reviewer、最新draft/version、approve、全checklistがtrue |
| 2 | `POST /api/v1/items/{id}/wordpress/draft` | 未送信ならeditorで実施。自動送信済みなら履歴を取得 |
| 3 | `POST /api/v1/items/{id}/wordpress/publish-approval` | publisher、draft_id、publication_id、confirm_publish=true |
| 4 | `POST /api/v1/items/{id}/wordpress/publish` | publisher、publish_approval_id等、最新version |

詳細なJSON項目は `/docs` と `app/contracts/wordpress_v1.py` / `editorial_v1.py` を参照する。各操作前に最新版を取得し、古い承認・版を使わない。WordPress管理画面で直接公開することは可能だが、システムの承認APIによる監査を通ったことにはならない。以後の照合で外部編集が検出される可能性がある。

## 10. 別モデルへ切り替える

1. 要求仕様と `docs/model-contracts.json` のプロンプト・型を確認する。
2. 現行Responsesアダプターに対応する場合は用途別モデルを `.env` で変更する。writerとverifierは異なるモデルとし、distinctチェックを維持する。
3. 別プロバイダーの場合は要求仕様のAIProvider実装境界に従ってアダプターを追加する。現行の `AI_PROVIDER` に未対応の名前を指定しても動かない。
4. 設定変更はAPIとschedulerへ同時に反映し、CLI利用時も同じ設定にする。既存画像はモデル設定を変えても自動で再生成しない。
5. 隔離環境で同じpackageに対して評価し、不正JSON、根拠のない数値・社名、比較不足、文体、資料番号、実モデル記録を確認する。
6. 旧モデルの検証・承認は無条件で流用しない。現在のprofile/policyに対する再検証が必要なら、`POST /api/v1/drafts/{draft_id}/verify` に最新 `expected_version` を指定する。

AI入力上限や出力上限を変える場合、`compose.yaml` で渡される変数とSettingsの許容範囲も確認する。画像生成は独立アダプターであり、文章モデル変更だけでは切り替わらない。

## 11. エラー対応・データ移行・バックアップ

| 症状・コード | 確認・対応 |
| --- | --- |
| `AI_NOT_CONFIGURED` | provider、キー、必要工程のmodel、再作成の反映 |
| `AI_MODELS_MUST_BE_DISTINCT` | 実際のwriterモデルとverifierモデルを分ける |
| `COMPARISON_MIN_SOURCES_REQUIRED` | 適合する検証済み資料を収集し、比較を再実行 |
| `DRAFT_SOURCE_SET_DUPLICATE` 等 | 既存の同じ資料集合の記事を確認。重複予約を無条件削除しない |
| `WORDPRESS_CATEGORY_MAPPING_REQUIRED` | 対象カテゴリのWordPress IDを設定 |
| 外部編集・hash不一致 | 人手変更を確認し、生成結果で上書きしない |
| `WORDPRESS_RECONCILIATION_PENDING` | 対象ID/slugを照合。未作成を確認する前にPOSTを繰り返さない |
| `WORDPRESS_MEDIA_RECONCILIATION_PENDING` | mediaのslugを照合。アップロードを無条件再送しない |
| 画像 `blocked` | 生成結果取得が不確実な場合、課金を伴う再生成を盲目的に繰り返さない |

AI検証エラーの詳細はjobs/itemsの `ai_runs.validation_errors` に出る。出力全文や秘密情報を診断ログへ追加しない。

`WORDPRESS_POST_TYPE` / `WORDPRESS_REST_BASE` の変更は送信先の切り替えであり、既存投稿の移動ではない。通常投稿からの移行は、対象・本文一致・公開状態・送信履歴を確認した個別作業になる。このセッションで行った移行スクリプトは `.local` 内の一回限りの運用補助であり、汎用移行機能として配布していない。

コードだけをcloneしても、既存記事・facts・監査・送信履歴・画像bytesは復元しない。これらはPostgreSQL、WordPressのDBとuploads、秘密設定に分かれている。移行時はschedulerを停止して書き込みをそろえ、PostgreSQLのバックアップ、WordPress DB/uploads、`.env` の別途安全な移送を用意する。送信履歴なしで既存記事を一括再送しない。Composeの `down -v` はDB volumeを削除するため、通常の更新手順に使わない。

## 12. 検証とモデル契約の更新

```powershell
docker compose --project-directory $projectRoot --profile test build test
docker compose --project-directory $projectRoot --profile test run --rm test
```

testサービスは外部AI・WordPressを無効にし、ruff、mypy、pytestを順に実行する。PostgreSQL統合試験は一意な試験schemaを使う。実サイトのテーマ・認証・表示は別途プレビューで確認する。

`model-contracts.json` は実装から抽出した静的な引き継ぎ資料である。更新用スクリプトは設定・DB・外部APIへ接続しない。ホストの開発環境で実行する場合:

```powershell
python -m tools.export_model_contracts --output docs/model-contracts.json
```

Python開発環境がない場合は、プロジェクトのtestイメージへスクリプトを標準入力で渡せる。共有フォルダー上でのPowerShell例:

```powershell
$contracts = Get-Content -LiteralPath (Join-Path $projectRoot 'tools\export_model_contracts.py') -Raw |
    docker compose --project-directory $projectRoot --profile test run --rm --no-deps -T test python - --output -
if ($LASTEXITCODE -ne 0) { throw 'Contract export failed' }
[IO.File]::WriteAllText((Join-Path $projectRoot 'docs\model-contracts.json'),
    ($contracts -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
```

promptやDTOを変えた場合はtestイメージも先にbuildし、JSONを更新してから文書と一緒にcommitする。
