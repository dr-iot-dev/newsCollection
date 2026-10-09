# News Weave（ニュースを編む）への名称変更

更新日: 2026-10-09（日本時間）。airlabs.jpの表示名・投稿者と、投稿タイプ・REST名の変更まで反映済み。記事をコピーせず、保存済みの投稿タイプとアプリ側の送信履歴を移行した。新規記事の公開は行っていない。

## 実サイトへの反映状況（2026-10-09）

- 投稿タイプは `news_weave`、REST名は `news-weave`、投稿用アカウントは `news-weaver`（ID 3、表示名 News Weaver）である。プラグインはNews Weave 1.2.0。旧REST `/wp-json/wp/v2/nc-news` は登録されずHTTP 404になる。
- 既存7記事（公開4・下書き3）とゴミ箱の検証記事87を新投稿タイプへ移行し、一覧ページ63のクエリーを更新した。記事ID・本文・状態・作者・画像・カテゴリ・タグ・日時・スラッグを保持した。公開記事のURL `/collected-news/{slug}/` と一覧 `/news/` も保持した。
- 送信履歴7件と重複防止予約7件を新送信先へ移行した。保存済みのスラッグを引き継ぐため、再送・承認・画像処理でも既存記事を扱える。画像7件と承認情報は保持した。
- `.env` の投稿タイプ・REST名を新名称に更新し、API・scheduler・collectの新コードをbuildした。APIとschedulerは新設定で再作成して停止状態を維持した。新ユーザーから新REST名へ下書き90を送信し、照合後にゴミ箱へ移した。
- 移行前バックアップと実サイト照合結果は `.local/news-weave-route-wordpress-before.json`、`.local/news-weave-routes-db-backup.dump`、`.local/news-weave-route-history-plan.json`、`.local/news-weave-route-history-applied.json`、`.local/news-weave-route-verification.json` に保存した。いずれもGit対象外である。

## 表示名・投稿者の先行変更（2026-10-09、投稿タイプ移行前）

- 現在の送信ユーザーは新規作成した `news-weaver`（ID 3、編集者）で、ニックネーム・ブログ上の表示名は `News Weaver` である。ユーザーが発行したアプリケーションパスワードを `.env` に設定し、認証と実際の下書き送信（投稿者ID 3）を確認した。検証用下書き87は確認後にゴミ箱へ移した。既存7記事は変更せず、以前の投稿者ID 2を維持する。
- APIとschedulerを新認証設定で再作成し、停止状態を維持した。`collect` は実行ごとに `.env` を読み込む。検証記録は `.local/news-weaver-verification.json` に保存した。
- 投稿用ユーザー（ID 2）のニックネームとブログ上の表示名を `news-weaver` に更新し、既存7記事の投稿者欄への反映を確認した。ログイン用ユーザー名 `news-integration` は標準管理画面で変更できないため維持し、投稿用の認証設定も維持した。
- 固定ページID 63 (`https://airlabs.jp/news/`) のタイトルを「ニュースを編む」、冒頭文を「『ニュースを編む』では、…」に更新した。スラッグ・公開状態・既存クエリーループは維持した。
- 公開ページとトップページを取得し、新タイトルとナビゲーションリンクの表示を確認した。旧表示名は公開ページのテキストに残っていない。
- 管理者のChromeタブから互換モードの `.local/news-weave-legacy.zip` をインストールし、旧 **News Collection Articles** を無効化、新 **News Weave 1.1.0** を有効化した。プラグインの実ファイルは `news-weave/news-weave.php`、管理画面の投稿表示名は「ニュースを編む」になった。旧プラグインは復旧用に無効のまま残した。
- 切り替え前後の既存7記事（公開4・下書き3）のID・投稿タイプ・状態・スラッグ・本文・タイトル・抜粋・カテゴリー・タグ・アイキャッチID・更新日時・リンクが一致した。公開一覧と公開4記事の既存URLすべてがHTTP 200で取得できた。
- `nc_news / nc-news / collected-news` は維持した。投稿者の認証情報だけを `.env` で更新した。互換モードは配布ZIP内で既定化し、`wp-config.php` は編集していない。APIとschedulerは切り替え前から停止しており、今回起動していない。
- 変更前のページ、更新計画と照合結果はGit対象外の `.local/news-weave-live-page-plan.json` と `.local/news-weave-live-page-proof.json` に保存した。プラグイン切り替えの前後照合は `.local/news-weave-plugin-before.json` / `.local/news-weave-plugin-after.json`、ZIPのハッシュと検証記録は `.local/news-weave-deployment-manifest.json` に保存した。

## 変更した名前

| 対象 | 新名称 |
| --- | --- |
| アプリケーション / Python配布パッケージ | News Weave / `news-weave` |
| CLI | `news-weave`（旧 `ai-iot-news` も互換コマンドとして使用可能） |
| WordPressプラグイン | News Weave |
| プラグインフォルダー / PHPファイル | `wordpress/news-weave/news-weave.php` |
| 管理画面の投稿表示名 / 一覧ページの新名称 | ニュースを編む |
| 新規導入の投稿タイプ内部名 / REST名 | `news_weave` / `news-weave` |
| 新規導入の個別記事URL | `/news-weave/{slug}/` |
| 固定ページブロック原稿 | `wordpress/news-weave-page.html` |
| 配布用ZIP | 新規導入 `.local/news-weave.zip` / 既存サイト `.local/news-weave-legacy.zip` |
| 設計書 | `ai_iot_news_weave_system_design.md` |

作業フォルダー `newsCollection` とGitHubリポジトリ名は変更していない。実行環境・保存先への参照を維持している。Docker Composeのプロジェクト名 `ai-iot-news` は既存のDB volumeを使うため維持した。新規環境で別名を使う場合は `docker compose -p news-weave ...` を使えるが、既存環境にそのまま指定すると別DB volumeになる。

収集用User-Agent `NewsCollectionBot` も現行の取得・robots確認に使われる名前として維持した。変更する場合は取得元の利用条件・robotsを新User-Agentで再確認し、`config/sources.yaml` を更新してDBへ同期する。

## 新しいサイトに導入する場合

1. `wordpress/news-weave` を新サイトの `wp-content/plugins/` へコピーするか、次のZIPを管理画面でアップロードする。

   ```powershell
   $projectRoot = '\\truenas\dev\codex\newsCollection'
   python (Join-Path $projectRoot 'tools\build_wordpress_plugin.py')
   ```

2. **News Weave** を有効化する。新規導入では `NEWS_WEAVE_LEGACY_ROUTES` は定義しない。
3. 投稿用ユーザーとアプリケーションパスワード、カテゴリー・タグを用意する。`.env` のURL・ユーザー・パスワード・カテゴリーIDを新サイト用に置き換える。
4. `.env` の投稿先を次の設定にする。APIとschedulerを再作成して設定を反映する。コード更新後はイメージの再buildも必要になる。

   ```dotenv
   WORDPRESS_POST_TYPE=news_weave
   WORDPRESS_REST_BASE=news-weave
   ```

5. `/wp-json/wp/v2/news-weave` と1件の下書き送信を確認する。
6. 一覧固定ページのタイトルを「ニュースを編む」、スラッグを `news` とし、`wordpress/news-weave-page.html` のブロック原稿を貼る。記事用 `/news-weave/` と一覧用 `/news/` を区別する。

詳しい設定・再作成・送信手順は [WordPress運用手順](setup-and-wordpress.md) を参照する。

## 既存サイトで記事・URL・送信履歴を維持する場合

既存の `nc_news` の記事は、プラグイン名を変えてもWordPress DBに `nc_news` として保存されている。REST名もアプリの送信先識別に含まれるため、名前を一括置換すると既存記事や送信履歴をそのまま使えなくなる。互換モードでは表示名とプラグインファイル名を更新し、既存の保存先とURLを維持する。

1. 切り替え中はAPIとschedulerを停止する。`.env` の `WORDPRESS_POST_TYPE=nc_news` と `WORDPRESS_REST_BASE=nc-news` は維持する。
2. 既存サイト用ZIPを作成する。このZIPは互換モードを既定にするため、`wp-config.php` の編集は不要である。通常のZIPで導入する場合は、代わりに `wp-config.php` のWordPress読み込み前（「編集が必要なのはここまでです」より上）へ下記の定数を追加する。

   ```powershell
   python (Join-Path $projectRoot 'tools\build_wordpress_plugin.py') --legacy
   ```

   ```php
   define('NEWS_WEAVE_LEGACY_ROUTES', true);
   ```

3. `.local/news-weave-legacy.zip` を「プラグイン → 新規追加 → プラグインのアップロード」でインストールする。旧 **News Collection Articles** を無効化してから、新 **News Weave** を有効化する。両方を同時に有効化しない。旧プラグインを無効化しても投稿データは削除されない。復旧用として旧プラグインを無効のまま残せる。
4. 管理画面の「ニュースを編む」に既存記事が表示され、REST `/wp-json/wp/v2/nc-news` と既存の `/collected-news/{slug}/` が使えることを確認する。必要なら「設定 → パーマリンク」を保存する。
5. 既存の一覧固定ページ（airlabs.jpではID 63）のタイトルを「ニュースを編む」に変更する。新しいブロック原稿を使う場合は、その中の `"postType":"news_weave"` を `"postType":"nc_news"` に変更してから貼る。既存クエリーループをそのまま使ってもよい。ページのスラッグ `news` は維持し、メニューやボタンの表示名も更新する。
6. 新しいコードをbuildし、既存のComposeプロジェクトでAPIとschedulerを起動する。

   ```powershell
   docker compose --project-directory $projectRoot up --build -d --wait
   docker compose --project-directory $projectRoot build collect
   ```

投稿タイプ・REST名も新名称へ移す場合は次の専用移行手順を使う。記事URLのベースも新名称へ変える場合はリンク・リダイレクトの移行が別途必要になる。今回の専用移行では既存URLを保持する。

## 既存サイトの投稿タイプ・REST名も移行する場合

移行中はAPI・schedulerと他の投稿処理を停止する。WordPressの記事・一覧ページとアプリDBをバックアップしてから行う。

1. 新しいコードをbuildし、既存サイト用のNews Weave 1.2.0 ZIPを作成してWordPress管理画面から更新する。既存サイト用ZIPは移行完了まで旧投稿タイプを登録する。

   ```powershell
   docker compose --project-directory $projectRoot build api scheduler collect
   python (Join-Path $projectRoot 'tools\build_wordpress_plugin.py') --legacy
   ```

2. アプリDBの移行をdry-runで確認する。移行先に既存の送信履歴・予約がある場合は中止する。

   ```powershell
   Get-Content (Join-Path $projectRoot 'tools\migrate_wordpress_routes.py') -Raw |
       docker compose --project-directory $projectRoot run --rm --no-deps -T collect python -
   ```

3. WordPressの「ツール → News Weaveの移行」で記事IDと一覧ページIDを確認し、「news_weave / news-weaveへ移行する」を実行する。管理者権限とnonceを確認し、InnoDBのトランザクションで記事の投稿タイプと一覧クエリーだけを変更する。途中で失敗した場合はロールバックする。
4. アプリDBの移行を適用する。送信先・重複防止キー・契約内の送信先とそのハッシュ、予約のscopeを更新する。記事のID・スラッグ・本文・画像・承認ハッシュは変更しない。移行監査イベントを追記する。

   ```powershell
   Get-Content (Join-Path $projectRoot 'tools\migrate_wordpress_routes.py') -Raw |
       docker compose --project-directory $projectRoot run --rm --no-deps -T collect python - --apply
   ```

5. `.env` を `WORDPRESS_POST_TYPE=news_weave`、`WORDPRESS_REST_BASE=news-weave` に変更する。URL・投稿用ユーザー・認証情報・カテゴリIDは保持する。
6. APIとschedulerを停止状態のまま新設定で再作成し、新RESTの全記事・一覧クエリー・公開URL・送信履歴・下書き送信を照合する。

   ```powershell
   docker compose --project-directory $projectRoot up --no-start --no-deps --force-recreate api scheduler
   ```

7. 運用を再開する場合にAPIとschedulerを起動する。今回の実サイト移行では停止状態を維持した。

WordPress側には移行前の記事IDと一覧ページ原稿を復旧用optionに保持する。アプリ側の送信先を戻す場合は移行ツールの `--rollback --apply` を使える。復旧前には移行後の記事追加やページ編集の有無を照合し、双方の状態を合わせる。

## 検証

```powershell
docker compose --project-directory $projectRoot --profile test build test
docker compose --project-directory $projectRoot --profile test run --rm --no-deps test
python (Join-Path $projectRoot 'tests\wordpress\run_checks.py')
```

`php:8.3-cli-alpine` イメージがローカルに必要である。PHP検証はWordPressの登録APIを代替して新旧の投稿タイプ・REST名・URL・表示名と有効化処理を確認する。実サイトのテーマ表示やサーバーの認証設定は別途確認する。
