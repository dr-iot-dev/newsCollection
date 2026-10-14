# 第12候補・C04比較記事の作成・検証記録

作成日：2026年10月14日。

記事：[セキュリティ運用AI3構成の文脈分析・対応起動と人の判断](comparison-article-c04-security-operations-20261014.md)

## 選定と比較範囲

3社のセキュリティ運用支援で、文脈データの統合、AIによる調査・優先順位、対応の連携と人の役割が説明されている。ServiceNowは6構成全体からインシデント対応部分へ限定する。

対象：F017 ServiceNow Agentic Incident Response、F140 Zscaler Agentic SOC、F303 Vectra AI次世代プラットフォーム。

セキュリティ担当者の調査・トリアージ・対応判断をAIで支援する構成の比較

元評価はneeds_reviewのまま保持した。最低類似度0.6754915856112303、平均0.6847790919468096。元の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。順位は既存の自動スコアの順位ではなく、原文の比較しやすさに基づく編集上の順序。

## 検証結果

原文の15 facts、15引用と文字位置を照合。決定的検査18項目合格、独立AI検証12項目全てpass。完成記事と検証原稿は一致。

比較表5行は全て2資料以上に根拠がある。未知セル0件。表に「資料で確認できず」が含まれる場合だけ注記を付ける条件を確認した。

本文等と原文の最長連続一致32文字。これは表を除く検査であり、法的な権利保証ではない。

編集回数：1。初稿はwriter-original.json、編集内容はeditorial-revision.jsonに保存。

## API使用量と保存先

本文生成：gpt-4.1-mini-2025-04-14。独立検証：gpt-4.1-2025-04-14。API実行2回。入力17645 tokens、出力2875 tokens。推定料金 USD $0.0386804（税・為替換算を除く推定値）。

使用量、プロンプト、構造化スキーマ、要求・応答、表セルの根拠、照合記録は ../.local/comparison-article-c04-twelfth-20261014/ に保存。APIキーと認証ヘッダーは保存していない。

既存API記事・比較報告書と元のC02/C24評価証跡476ファイルのSHA-256が不変。記事はローカルファイルに保存した。

2026年10月14日確認の[GPT-4.1 mini公式単価](https://developers.openai.com/api/docs/models/gpt-4.1-mini)と[GPT-4.1公式単価](https://developers.openai.com/api/docs/models/gpt-4.1)により推定。API利用条件は[Structured Outputs公式資料](https://developers.openai.com/api/docs/guides/structured-outputs)を参照。
