# 電子工作・モバイル2,000件の収集・選定・生成・検証記録

このディレクトリはユーザー指定の一度の実行記録であり、通常運用の仕様・取得条件ではない。現行仕様はルートREADMEと `docs/seven-stage-system-design-20261015.md` に従う。2026年10月15日、日本時間。

## 結果

- 取得条件: 「電子工作」「モバイル」を優先し、AI/IoT必須条件を外した。「商品サービス」種類01と111語のタイトル除外は維持。2語の合計2,000件をURLで重複排除（399件・1,601件）。
- 企業ごとの最新696件を実モデルで埋め込み、29クラスター（ノイズ226件）へ分類。GPT-4.1で本命のみ11、本命・予備4、選定不可14。
- GPT-6.1 Solで本命15組と、生成不適時の予備1組を処理。7本を生成、8クラスターは生成不適。
- GPT-6 Astraで全7本を独立検証。採用可6本（92〜94点）、1本は同じ組で1回修正・再検証しても不適（49点）。選定・埋め込みは再送していない。
- 採用可6本に対応する横長イラストを内蔵image_genで作成。PNG6枚と最終プロンプト、代替テキスト案を保存。

|モデル|実使用量×公開USD単価|
|---|---:|
|text-embedding-3-small|$0.036317|
|gpt-4.1-2025-04-14|$2.060084|
|gpt-6.1-sol（修正含む）|$0.556000|
|gpt-6-astra（再検証含む）|$1.385820|
|計測済み合計|$4.038221|

請求書の確定額ではない。残高不足で失敗した1要求は使用量が返らず費用未確定（0扱いにしない）。内蔵画像生成も使用量・課金額を取得できず未計測。途中のAPI残高不足から保存済み成功結果を再利用して再開し、生成・検証は完了した。

## 保存物

- [選定結果](outputs/selections.md)・[選定実行レポート](outputs/report.md)
- [生成・検証の最終結果と記事](outputs/generation-sol-astra-20261015/report.md)
- [モデル別・工程別コスト](outputs/generation-sol-astra-20261015/costs.md)・[使用量と費用JSON](outputs/generation-sol-astra-20261015/costs.json)
- [アイキャッチ6枚・代替テキスト案](outputs/wordpress-featured-images/README.md)
- [DBの区別と接続先](outputs/database-guide.md)・[生成DBの利用方法](outputs/generation-sol-astra-20261015/database-guide.md)
- [収集・選定の照合記録](outputs/verification.json)・[生成・検証のAPI入力とDBの照合](outputs/generation-sol-astra-20261015/reconciliation.json)

## DB・API原文と再現用ソース

大容量SQLite3ファイル（収集監査・選定・生成）とAPI要求/応答原文はGitに格納せず、実行したPCの次の場所に保持する。

```text
C:/Users/driot/Documents/Codex/2026-10-15/pr-times-2000-db-db-db/outputs/
```

DBの接続URLと実行IDは上記DBガイドに記録した。従来のPostgreSQL・旧SQLiteは変更せず、選定用と生成用の新DBも分離して保持した。選定DBのSHA-256不変、生成DBのintegrity_check・foreign_key_check、全生成本文の独立検証と実返却モデルを照合済み。

`work/` は今回の実行スクリプトの保存コピー。環境固有のUNC参照とAPIキーの読込先があるため、別環境での無条件実行はしない。キーそのものや.envは含まない。実行時のアプリ・テストは `outputs/generation-sol-astra-20261015/execution-source.zip` の `runtime/` に保存した。再現時にその `runtime/` を `work/runtime/` へ展開し、依存環境とDB・保存API原文を用意する。JSON内の実行PCの絶対パスは来歴として保持しており、他環境では読み替えが必要。

GitにはPNG原本のみを格納し、ダウンロード用の重複ZIPはローカル出力に保持した。検証用のRuff対象は現行app/tests。今回のアプリ変更は通常条件を変えず、明示的なドメイン条件解除、選定後停止、選定ステータスの組数説明を追加している。
