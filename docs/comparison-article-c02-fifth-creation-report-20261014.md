# 第5候補・C02比較記事の作成・検証記録

作成日：2026年10月14日。

記事：[設備の稼働監視3構成のデータ収集・可視化と保守・実績管理への接続](comparison-article-c02-equipment-monitoring-20261014.md)

## 選定と比較範囲

C02の既存API評価で全3ペア比較可能と共通用途が確認された唯一の組。原文では保守対応への接続、導入先向けダッシュボード、プレス機の実績収集の違いを説明できる。最低類似度は閾値未満のため自動採用を解除せず編集候補として選ぶ。

対象：F007 esm IoT、F039 CLOUDSHIP＋RealBoard構成、F234 Smart Kaizen Counter（SKC）。

工場等の設備稼働データを収集・蓄積し、リアルタイムに可視化して次の業務へつなぐ仕組み

元評価はneeds_reviewのまま保持した。最低類似度0.5338902780672479、平均0.6008031572398475。元の保留理由：similarity_below_threshold。順位は既存の自動スコアの順位ではなく、原文の比較しやすさに基づく編集上の順序。

## 検証結果

原文の22 facts、25引用と文字位置を照合。決定的検査18項目合格、独立AI検証12項目全てpass。完成記事と検証原稿は一致。

比較表6行は全て2資料以上に根拠がある。未知セル1件。表に「資料で確認できず」が含まれる場合だけ注記を付ける条件を確認した。

本文等と原文の最長連続一致25文字。これは表を除く検査であり、法的な権利保証ではない。

編集回数：1。初稿はwriter-original.json、編集内容はeditorial-revision.jsonに保存。

## API使用量と保存先

本文生成：gpt-4.1-mini-2025-04-14。独立検証：gpt-4.1-2025-04-14。API実行2回。入力18933 tokens、出力2664 tokens。推定料金 USD $0.0389476（税・為替換算を除く推定値）。

使用量、プロンプト、構造化スキーマ、要求・応答、表セルの根拠、照合記録は ../.local/comparison-article-c02-fifth-20261014/ に保存。APIキーと認証ヘッダーは保存していない。

既存API記事・比較報告書と元のC02/C24評価証跡440ファイルのSHA-256が不変。記事はローカルファイルに保存した。

2026年10月14日確認の[GPT-4.1 mini公式単価](https://developers.openai.com/api/docs/models/gpt-4.1-mini)と[GPT-4.1公式単価](https://developers.openai.com/api/docs/models/gpt-4.1)により推定。API利用条件は[Structured Outputs公式資料](https://developers.openai.com/api/docs/guides/structured-outputs)を参照。
