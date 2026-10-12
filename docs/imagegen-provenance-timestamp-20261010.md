# imagegenの識別情報表示（2026-10-10）

組み込みimagegenの過去の実行記録にはモデル名・バージョンが含まれていなかったため、モデル名を推測しない。従来の「imagegen (モデル名未提供)」を「imagegen（画像登録日時: YYYY-MM-DD HH:mm:ss JST）」へ変更した。

表示時刻は、画像の内容ハッシュと一致する最初のimage.asset_import_intent監査記録に基づく。正確な生成完了時刻が保存されていないため「生成日時」ではなく「画像登録日時」と明示する。画像を別の原稿へ引き継いだ際のFeaturedImage.created_atや記事更新日時を使わない。登録記録がない場合は推測せず「画像登録日時の記録なし」と表示する。

既存9件（5663、5664、5665、5666、5667、5678、5679、5680、5687）の下書きを更新。本文、比較表、出典、執筆・検証モデル、既存画像、記事ID、投稿者は維持。今後の画像取り込みと投稿パッケージ検証も同じ表示関数を使う。

- 変更前のバックアップ: .local/imagegen-timestamp-backup.jsonl
- 更新結果: .local/imagegen-timestamp-updated.jsonl
- 検証: Ruff成功、Mypy103ファイル成功、関連テスト125 passed / 1 skipped
