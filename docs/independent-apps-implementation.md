# 機能分離版の起動と移行

更新日: 2026-10-12。コードの実装手順であり、稼働中サービス・既存 WordPress 投稿にはまだ適用していない。

## 独立した二つのアプリ

NewsWeave は収集、根拠整理、比較、執筆、検証、画像、完成原稿の保存を担当する。
WordPress の資格情報・送信 API・送信スケジューラーは持たない。
WPuploader は完成した .nwdraft を読み、WordPress に下書きとして保存する。
生成側の PostgreSQL、AI、コードを必要としない。

生成側の統合 DB アプリは既存の編集フローを保つ。七つの単独工程は
components/collect、ground、curate、write、verify、illustrate、assemble にある。
各フォルダーを単独で pip install でき、隣の工程も親の app パッケージも要求しない。
DB 統合フローは保存済み原稿から独立 assemble/illustrate を呼ぶ adapter を使う。
全 DB フローの実行制御を七つの CLI に置換することは、この初版では行っていない。

## 生成側

統合アプリは従来どおりインストールし、新しい DB migration を適用する。

~~~console
alembic upgrade head
news-weave drafts preview <draft_id>
news-weave drafts export <draft_id> --output article.nwdraft
news-weave drafts export-pending
~~~

成果物のローカル保存先は DRAFT_ARTIFACT_DIR。既定は OS のユーザーデータディレクトリで、
Docker は /data/drafts のローカル named volume を使用する。
DRAFT_TRANSFER_DIR を空にすれば、アップローダーや共有フォルダーがなくても保存できる。
共有時は <DRAFT_TRANSFER_DIR>/ready/ に完成ファイルを atomic rename で配置する。

不足資料の外部検索・取得・更新は FETCH_MISSING_SOURCES=false が既定。
有効にする場合だけ true を指定する。既存の RESEARCH_REFRESH_SOURCES=true では有効にならない。
通常の登録ソース収集と、手元資料の利用は継続する。資料不足は needs_input と理由を返す。
FEATURED_IMAGES_ENABLED=false で画像を使わず完成原稿を作成できる。

画像生成の応答が不明な場合は自動再課金を停止する。前の生成が停止したことを確認した場合のみ
drafts retry-image <draft_id> --confirmed-generation-stopped を実行する。
レビュー必須の場合は本文の承認に加え、生成画像を確認し drafts approve-image を使う。

## 七つの単独工程

~~~console
python tools/build_generation_components.py
pip install ./components/ground
nw-ground run --request request.json --output <ローカル結果保存先> --config stage.toml
~~~

全工程が同じ Request/Result 形式を使用する。Request の inputs は role ごとの
file と sha256 だけで、ZIP 内に必要な原文・根拠・モデル記録を含める。
Request の file は request.json のディレクトリ内の相対パス。
Result の file は実行先の絶対パスなので、別ホストへ移すときはファイルをコピーして次の
Request に相対パスと既存の hash を指定する。DB ID の解決は不要である。

~~~json
{"schema_version":"1.0","module":"ground","inputs":{"sources":{"file":"sources.nwstage","sha256":"sha256:<64桁>"}},"parameters":{"facts_mode":"rules"}}
~~~

config は TOML、資格情報は環境変数 AI_API_KEY。
writer/verifier には [models] の writer/verifier を指定し、異なるモデルを使用する。
設定に fetch_missing_sources=true を指定した場合も、Request 側の false でその実行を停止できる。
Request true は実行側 false を解除できない。CLI の --fetch-missing-sources は実行側の明示設定である。
結果の終了コードは success=0、needs_input=10、rejected=20、error=30。
完了結果は入力・設定の hash で再利用し、不明な AI 試行は安易に再実行しない。

各工程の入力 role と契約は [生成設計](article-generation-module-plan-20261012.md) と
[protocols](../protocols/README.md) を参照する。

## 受け渡しとアップローダー

WPuploader の [README](../../WPuploader/README.md) に従い、独立してインストールする。
生成側は原稿を変更しない。アップローダーは共有原稿を読み取り、ローカル cache と SQLite で管理する。
任意の処理通知は receipts/ に書き戻す。生成側は通知がなくても正常終了する。
通知の生成側 UI への統合は初版には含めない。

SQLite は DELETE journal、FULL 同期、短い transaction と OS の排他ロックを使用する。
SQLite、cache、lock は SMB/NFS に置かない。一つの投稿先の active uploader は一つの
実行ホスト・台帳に固定する。二つのアプリの同時動作と、同一台帳を使う複数起動に対応する。
別ホストの空台帳から同じサイトへ同時投稿する運用は対象外である。

Docker で共有する場合は両リポジトリの compose.transfer.yaml を重ね、
DRAFT_TRANSFER_HOST に同じ host directory を指定する。ready/ と receipts/ を用意する。
共有なしの compose は他方のサービスも共有フォルダーも要求しない。

## 現在の送信履歴を引き継ぐ順序

1. 旧送信スケジューラー・API を停止し、進行中の送信がなくなったことを確認する。
2. 生成側 DB とローカル成果物をバックアップし、新 DB migration を適用する。
3. 現行 post/posts または news_weave/news-weave の target_id に対し、
   news-weave drafts export-history --target <target_id> --output history.json を実行する。
4. WPuploader の新規台帳を明示初期化し、migrate-history history.json を実行する。
   この段階では CMS 書き込みを行わない。
5. 認証・投稿先・カテゴリ ID を設定し、reconcile で既存 ID・slug・raw payload を照合する。
   原稿 cache を別途 import しても、履歴の既知 ID を使い新規作成しない。
6. 不明履歴は個別解決し、dry-run を確認してから run-once/watch を有効にする。

旧投稿タイプの互換コード・移行画面・CLI は削除済み。新プラグインは WPuploader の
wordpress/news-weave にあり、対応タイプは news_weave/news-weave。
Publication/FeaturedImage 等の既存 DB テーブルは履歴保持と既存画像再利用のため残す。
新しい生成・送信の実行状態は DraftExport/DraftAsset と uploader のローカル台帳に記録する。

## 復旧と限界

共有ファイル・通知の再配置は反復実行で回復する。投稿 POST の応答消失は GET で照合し、
一致すれば再開する。見つからない場合、その記事だけ uncertain で保留する。
標準 WordPress REST は exactly-once を保証しないため、無条件の再 POST は行わない。
人が編集・公開・削除した投稿を自動上書きしない。新しい版は明示 replace が必要となる。
明示 replace の変更検査と CMS 更新の間には標準 REST による原子的比較更新の保証がないため、
置換時は CMS 編集を同時に行わない。

台帳の紛失・物理破損は反復起動だけでは直らない。整合 backup を復元し、
recover --confirm-reconciliation-only で送信意図を照合専用に戻してから reconcile する。
不明操作を再許可する resolve は、運用者が remote 未作成を確認した場合に限る。

## 実装検証

pytest は AI/CMS の fake と隔離したテスト DB を使い、稼働サイトへ書き込まない。
tools/check_generation_components.py は実 wheel を build し、親アプリ・他工程・SQLAlchemy の
import を禁止して実行する。配布時は生成コードを更新してからこの検査を実行する。

復旧モードは台帳に保存するため、後から届く原稿も照合専用になる。
投稿・画像を照合または個別解決した後、finish-recovery --confirmed-history-reconciled で解除する。
未解決操作が残る間は解除できない。画像の個別解決は resolve-media の
--adopt-media-id または --confirmed-not-created を使う。

2026-10-12 の検証: 全体 830 passed / 1 skipped（隔離 PostgreSQL・SQLite）、
最終追加箇所 29 passed、WPuploader 35 passed、mypy 130 source files、ruff、
七つの wheel の独立実行、生成 bundle→独立 uploader wheel、Windows の OS lock/NAS 排除、
PostgreSQL migration、現行 PHP plugin、共有あり・なしの Compose 設定を確認した。
実サイトへの POST と実 AI 呼び出しは試験に使用していない。
