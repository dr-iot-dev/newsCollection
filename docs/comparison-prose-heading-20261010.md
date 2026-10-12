# 比較本文の見出し追加（2026-10-10）

kunsen.net の既存下書き9件（5663、5664、5665、5666、5667、5678、5679、5680、5687）で、比較表の注記の直後・比較本文の前に「比較の考察」のH2見出しを追加した。

記事構成は「簡潔な説明 → 比較表と注記 → 比較の考察（比較本文） → 出典 → 使用したAIモデル」。今後の生成でもシステムが見出しを付け、比較表と本文の境界が正しいことを検証する。見出しを欠いた原稿は投稿前に停止する（verification-v10）。

比較本文・リード・タイトル・資料群・全44行の比較項目・価格条件などの事実を保持した。3件の表内の語尾は既定のである調へ整えた。投稿者News Weaver、記事ID、スラッグ、アイキャッチ、画像登録日時を保持し、下書きのまま更新した。

収集資料が新しい版になっていた2記事については、4資料の既存30事実を現行の収集原文と完全一致する引用で再照合し、同じ資料群の根拠IDを更新した。比較表の値が同一であることを確認し、文章の書き直しは行っていない。

全9件が独立したgpt-4.1による12項目と通常の承認検証に合格。執筆モデルは元のgpt-5.2実行記録を保持している。

検証: Ruff成功、Mypy103ファイル成功、関連テスト72 passed / 2 skipped。APIとschedulerを更新版で再開する。

復旧・監査記録:
- 更新前のWordPress内容: .local/comparison-heading-backup.jsonl
- 資料版の照合記録: .local/comparison-heading-evidence-refresh.jsonl
- 原稿の検証記録: .local/comparison-heading-verifications.jsonl
- WordPressの反映結果: .local/comparison-heading-wordpress-updated.jsonl
- テスト結果: .local/test-comparison-heading.log
- 確認画面: news-weave-comparison-prose-heading.png（Codexのvisualizationsフォルダ）

newsCollection側の.env、compose.yamlのハッシュは前回値と一致する。
