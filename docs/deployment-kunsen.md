# kunsen.net用の独立したNews Weave環境

作成日: 2026-10-09（日本時間）。コードの元はcommit 7a2e56e。

| 項目 | newsWeave | newsCollection |
| --- | --- | --- |
| 作業ディレクトリ | `\\truenas\dev\codex\newsWeave` | `\\truenas\dev\codex\newsCollection` |
| WordPress | https://kunsen.net | https://airlabs.jp |
| Composeプロジェクト | `news-weave` | `ai-iot-news` |
| API | http://127.0.0.1:8001 | http://127.0.0.1:8000 |
| DB volume | `news-weave_postgres-data` | `ai-iot-news_postgres-data` |
| 投稿ユーザー | `news-weaver` / News Weaver（ID 2） | `news-weaver` / News Weaver（ID 3） |
| 投稿タイプ / REST名 | `news_weave` / `news-weave` | `news_weave` / `news-weave` |

newsWeaveは独立したGit clone、.env、DB、Dockerネットワークとコンテナを持つ。旧環境のDB・記事・送信履歴・画像・内部APIアカウントはコピーしていない。AIモデル・収集元の設定は引き継いだ。WordPress認証情報とDBパスワードは新環境用である。旧環境の.envとcompose.yamlを保持した。

## 起動・停止

PowerShellではUNCを作業ディレクトリにせず、`--project-directory` を明示する。

```powershell
$newsWeaveRoot='\\truenas\dev\codex\newsWeave'
docker compose --project-directory $newsWeaveRoot up -d --build api scheduler
docker compose --project-directory $newsWeaveRoot ps
Invoke-RestMethod http://127.0.0.1:8001/health/ready
```

停止する場合:

```powershell
docker compose --project-directory $newsWeaveRoot stop api scheduler
```

airlabs.jp用を起動する場合:

```powershell
$newsCollectionRoot='\\truenas\dev\codex\newsCollection'
docker compose --project-directory $newsCollectionRoot up -d api scheduler
```

プロジェクト名・APIポート・DB volumeが別なので同時起動できる。`-p` で相手のプロジェクト名を指定しない。

## WordPress

kunsen.netに新規導入用News Weave 1.2.0を有効化。旧ルートの互換モードは使用しない。アプリケーションパスワードはこの環境の.envだけに保存する。

```dotenv
WORDPRESS_BASE_URL=https://kunsen.net
WORDPRESS_POST_TYPE=news_weave
WORDPRESS_REST_BASE=news-weave
WORDPRESS_USERNAME=news-weaver
WORDPRESS_CATEGORY_MAP={"generative_ai":212,"edge_ai":213,"iot_platform":214,"security":215,"standards":216}
WORDPRESS_TAG_MAP={}
```

新環境に7件の収集元を登録済み。PR TIMESの6件（IoT、電子工作、生成AI、セキュリティ、IoTプラットフォーム、AIエージェント）はapproved、日経の1件はpendingのまま保持し、schedulerの自動収集対象から除外する。schedulerは収集、記事生成・検証、検証済み下書き送信、画像添付を行う。公開には明示的な承認が必要で、通常運用は下書きまでである。新しい記事を公開一覧に表示する固定ページ・メニューは今回の下書き接続設定には含まない。

歴史的なairlabs.jpへの導入記録は `docs/rename-to-news-weave.md` に残している。実環境の指定はこの文書と.env / compose.yamlを使う。

## 秘密設定と検証記録

.env、.local、認証情報、実サイト照合結果はGit対象外。環境分離の証跡は `.local/deployment-isolation.json`、接続検証の結果は `.local/kunsen-wordpress-verification.json` に保存する。

## 接続検証と稼働状況（2026-10-09）

kunsen.netのPHP実行方式を8.3 CGI版から8.3モジュール版へ変更した。ApacheにはAuthorizationヘッダーが届いていたがCGIのPHPには渡らず、外部REST認証がHTTP 401になっていた。変更反映後はPHP SAPIがapache2handlerとなり、news-weaverの認証と下書き・画像送信に成功した。www.kunsen.net、airlabs.jp、その他ドメインのPHP設定は変更していない。

.htaccessは診断用設定を取り除き、バックアップと同じ元の内容・UTF-8へ復元した。一時診断PHPは実行しない.txt記録へ変更し、元のPHP URLはHTTP 404を確認した。

実送信で確認した内容:

- 下書きID 5660: `[接続確認] News Weave — kunsen.net`
- 投稿者: news-weaver / News Weaver（ID 2）、状態: draft
- アイキャッチ画像: メディアID 5661、カテゴリー: 生成AI（212）
- 匿名RESTリクエストでは下書きが表示されない。
- 既存の公開投稿176件は維持され、サイトトップはHTTP 200。

APIは8001番で起動し、/health/readyがdatabase: okを返す。DBもhealthy。schedulerを起動し、PR TIMESから新規5件の収集成功を確認した。以後は通常の収集・生成・検証・下書き送信処理を行う。接続確認用の下書きはWordPressにだけ置き、既存記事の移行としてアプリDBには登録していない。

newsCollectionの.envとcompose.yamlはSHA-256で変更がないことを確認した。DB volumeは分離され、旧環境の送信履歴15件・重複予約24件を保持している。旧APIとschedulerは作業前と同じ停止状態。起動すればairlabs.jp用として動作する。

検証結果は.local/kunsen-wordpress-verification.json、.local/kunsen-auth-diagnostic.json、.local/deployment-isolation.json。airlabs.jpの既存認証と下書きRESTルートも読み取りでHTTP 200を確認し、.local/airlabs-preserved-verification.jsonに保存した。

内部APIの利用者アカウントはコピーしていない。認証が必要な管理APIを使用する場合は、別途この環境のアカウント設定が必要である。schedulerの通常運転とWordPressの下書き送信は稼働済み。
