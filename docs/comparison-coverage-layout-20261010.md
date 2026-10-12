# 比較資料の過半数条件と記事構成の変更（2026-10-10）

kunsen.net の既存9件を同じ記事IDの下書きとして更新した。各記事は異なるURLの3資料を比較し、44行すべてで2資料以上の特徴が出典付きで示される。元の記事の比較項目はすべて保持した。不足項目を削除する代わりに、用途・製品種別が適合する資料群を選び直した。

記事順は「簡潔な導入 → 比較表 → 比較の文章 → 出典 → 使用したAIモデル」に統一。本文作成・編集はgpt-5.2、独立検証はgpt-4.1で、9件すべて全12基準に合格した。表の事実は原資料の引用位置・値を検証した編集結果を使用し、記事末尾にも実際の処理とモデルを表示する。

投稿者News Weaver（ユーザーID 2）、既存アイキャッチ、記事ID、スラッグを維持した。更新前のローカル履歴とWordPress内容は保存され、旧Publicationはsuperseded、新Publicationはdrafted。既存の公開記事と接続確認用下書き5660は変更していない。

| 記事ID | タイトル | 比較資料・製品 | 各項目の記載資料数 |
|---|---|---|---|
| [5663](https://kunsen.net/wp-admin/post.php?post=5663&action=edit) | 業務自動化向け生成AI支援の実行設計と接続範囲 | AIプラットフォーム構築支援、Tsuguvi、Tripbox | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 2/3、対応・連携: 3/3 |
| [5664](https://kunsen.net/wp-admin/post.php?post=5664&action=edit) | IoT通信と設備監視の運用要件の違い | MEEQ（ミーク）、ハサレポ、BLAS | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 3/3、対応・連携: 3/3、価格と適用条件: 2/3 |
| [5665](https://kunsen.net/wp-admin/post.php?post=5665&action=edit) | 現場データ管理サービスの利用端末と連携基盤 | BLAS、IoTプラットフォームサービス、Nobest-Tag | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 2/3、対応・連携: 2/3 |
| [5666](https://kunsen.net/wp-admin/post.php?post=5666&action=edit) | 脆弱性診断サービスの対象範囲とAI運用の違い | Web・ネットワーク脆弱性診断（無料）、AI脆弱性診断支援サービス、AI脆弱性診断サービス | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 2/3、対応・連携: 3/3、価格と適用条件: 2/3、標準: 2/3 |
| [5667](https://kunsen.net/wp-admin/post.php?post=5667&action=edit) | 脅威・脆弱性対策サービスの対象範囲と運用像 | MIKAGURA（ミカグラ）、Web・ネットワーク脆弱性診断（無料）、AI脆弱性診断サービス | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 2/3、対応・連携: 3/3、価格と適用条件: 3/3、標準: 2/3 |
| [5678](https://kunsen.net/wp-admin/post.php?post=5678&action=edit) | 機器運用・現場管理ツールの利用端末と連携先 | VALUE Cube、BLAS、Nobest-Tag | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 3/3、対応・連携: 3/3 |
| [5679](https://kunsen.net/wp-admin/post.php?post=5679&action=edit) | LTE前提の設備遠隔監視とIoT通信管理の選び方 | ハサレポ、MEEQ（ミーク）、obniz Now | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 3/3、対応・連携: 3/3、価格と適用条件: 2/3 |
| [5680](https://kunsen.net/wp-admin/post.php?post=5680&action=edit) | LTE・SIM前提のIoT運用支援とデータ活用 | obniz Now、MEEQ（ミーク）、SORACOM Query | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 3/3、対応・連携: 3/3、価格と適用条件: 2/3 |
| [5687](https://kunsen.net/wp-admin/post.php?post=5687&action=edit) | 生成AI業務支援の実行設計と引き継ぎ動線 | Automation機能、VAAP 緊急AI問い合わせ窓口Suite（仮称）、Tsuguvi | 提供元: 3/3、技術・機能仕様: 3/3、ソフトウェア・通信要件: 2/3、対応・連携: 3/3、価格と適用条件: 2/3 |

## 今後の生成処理

- URL単位で重複を除き、全行の記載資料数が floor(資料数/2)+1 以上かを執筆前・検証時・投稿承認時に確認する。4資料なら3資料以上が必要。
- 候補資料を複数保存し、同社従来製品・他社製品を組み合わせて最終資料群の充足率を確認する。手動指定資料を保持し、低順位でも条件を満たす適切な資料を選ぶ。
- 再選定後も元の比較項目を引き継ぐ。資料に記載がない項目も保持され、過半数に達しなければ執筆・投稿を止める。
- 表は検証済み事実から先頭に生成し、本文の前に比較表があることを検証する。
- 事実抽出の上限を24件に拡張し、価格条件・前提条件・対応範囲を抽出する。言語や特許等を提供地域・標準と取り違えないよう指示を改善した。

## 検証・復旧記録

- 元のWordPress内容: .local/majority-wordpress-backup.jsonl
- 9件の反映結果・検証ID・行別充足率: .local/majority-wordpress-updated.jsonl
- 最終資料群: .local/majority-comparison-final-audit.jsonl
- 静的・型・全体テスト: .local/test-majority-final.log
- 修正後のブラウザプレビュー: news-weave-comparison-table-first.png（Codexのvisualizationsフォルダ）

newsCollection側の.envとcompose.yamlのハッシュが前回値と一致することを確認した。airlabs.jpへの既存構成は保持する。

最終検証: Ruff成功、Mypy 103ファイル成功、全体テスト625 passed / 3 skipped（2026-10-10）。
