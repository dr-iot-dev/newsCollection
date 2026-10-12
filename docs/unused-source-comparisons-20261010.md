# 未使用資料による新しい比較記事3件（2026-10-10）

kunsen.net に3件の比較記事を下書きとして保存。投稿者は news-weaver（WordPressユーザーID 2）。既存記事の更新は行っていない。

## 資料の選定と検証

- 作業開始時点のWordPress下書き10件と、ローカルの比較原稿の全履歴を照合し、使用済み23URLを除外した。除外基準は `.local/new-comparisons-exclusion-baseline.json` に保存。
- 新たに13件のニュース資料を取得し、比較軸と資料の充足状況から9件を採用した。3記事間にも同じ出典URLはない。
- 各記事は3資料を比較し、表示した全15比較項目で2資料以上の特徴を確認した。比較項目の不足を項目削除で回避していない。
- 本文作成は gpt-5.2、独立した原稿検証は gpt-4.1。全3件で12項目すべて合格。事実抽出の編集前AI使用履歴も表示。
- アイキャッチは gpt-image-1.5、1536×1024。淡いカテゴリ背景と自然な前景色を画像で確認した。
- 比較表 → 比較の考察 → 出典 → 使用したAIモデル、の順序をWordPress保存内容で再確認。

## 保存済み下書き

### MCP接続で公的情報を扱う業務支援サービス視点

- 投稿ID: 5746 / アイキャッチID: 5749
- 管理画面: https://kunsen.net/wp-admin/post.php?post=5746&action=edit
- 原稿ID: `d8f5e2bd-077a-460e-9137-1b07748d6d36`
- 状態: draft / 検証: 12項目すべてpass
- 比較項目の資料充足: 提供元 3/3、技術・機能仕様 3/3、ソフトウェア・通信要件 2/3、対応・連携 3/3、価格と適用条件 2/3、発売・提供開始時期 3/3、標準 3/3
- 出典:
  - https://prtimes.jp/main/html/rd/p/000000022.000158873.html
  - https://prtimes.jp/main/html/rd/p/000000001.000191307.html
  - https://prtimes.jp/main/html/rd/p/000000024.000161935.html

### 現場データ起点の自動化・監視・換気制御の設計軸

- 投稿ID: 5747 / アイキャッチID: 5750
- 管理画面: https://kunsen.net/wp-admin/post.php?post=5747&action=edit
- 原稿ID: `0ce741f8-a342-4ae8-831a-177116073e0f`
- 状態: draft / 検証: 12項目すべてpass
- 比較項目の資料充足: 提供元 3/3、技術・機能仕様 3/3、対応・連携 3/3
- 出典:
  - https://prtimes.jp/main/html/rd/p/000000250.000035514.html
  - https://prtimes.jp/main/html/rd/p/000000020.000087711.html
  - https://prtimes.jp/main/html/rd/p/000000046.000064082.html

### Web脆弱性診断サービスの診断方式と改修支援

- 投稿ID: 5748 / アイキャッチID: 5753
- 管理画面: https://kunsen.net/wp-admin/post.php?post=5748&action=edit
- 原稿ID: `f9ee7048-fd76-40bd-9232-d16702179293`
- 状態: draft / 検証: 12項目すべてpass
- 比較項目の資料充足: 提供元 3/3、技術・機能仕様 3/3、対応・連携 3/3、価格と適用条件 2/3、発売・提供開始時期 2/3
- 出典:
  - https://prtimes.jp/main/html/rd/p/000000002.000189790.html
  - https://prtimes.jp/main/html/rd/p/000000389.000023654.html
  - https://prtimes.jp/main/html/rd/p/000000004.000108150.html

## 実行時に修正した処理

- APIキーの本数など通常の製品仕様を指示注入として誤判定していた規則を修正。APIキーの開示指示などは引き続き拒否する。
- MCPによる公的情報接続、Webシステム、センサー・設備データなどを比較テーマ判定で扱えるようにした。目的・環境・機能の一致条件は維持。
- 診断や監視の発表資料にある敬体の語尾を、出典の引用を保持しつつ比較表では常体に変換する。
- 事前の関連117テスト、および最終の文体・表・原稿・送信・AI表記テストが成功。Ruff成功、Mypy103ファイル成功。
- 今回の参照用・不採用資料から追加の記事が自動作成されないよう、今回生成された参照資料の処理待ち45件のみcancelledにし、理由と監査記録を保存。資料・事実・原稿・検証履歴を削除していない。
- newsCollection側の.envとcompose.yamlのSHA-256が作業前と一致。airlabs.jp用設定は保持。

## 証跡

- `.local/unused-three-wordpress-drafts-20261010.jsonl`
- `.local/unused-three-final-proof-20261010.json`
- `.local/unused-three-featured-images-20261010.jsonl`
- `.local/unused-three-regression-checks-20261010.log`
- `.local/unused-three-reference-queue-20261010.jsonl`
