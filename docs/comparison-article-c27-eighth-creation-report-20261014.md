# 第8候補・C27比較記事の作成・検証記録

作成日：2026年10月14日。

記事：[AI映像監視3タイプの検知対象・警戒設定とイベント後の運用](comparison-article-c27-ai-surveillance-20261014.md)

## 選定と比較範囲

人物・車両の検知、警戒設定、撮影方式、運用条件に違いがある。F278はMF2Aへ限定し、F902は自然言語検知の対象と明記されたXシリーズ上位2機種を1対象群として扱う。

対象：F278 AZx MF2A、F711 TSD-4FMS-IPC、F902 i-PRO Xシリーズ上位2機種。

施設・現場の映像監視で、検知対象の設定とイベント後の運用を比べる。固定式・デュアルレンズ・全方位を区別

元評価はneeds_reviewのまま保持した。最低類似度0.567348531145726、平均0.6483172049717475。元の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。順位は既存の自動スコアの順位ではなく、原文の比較しやすさに基づく編集上の順序。

## 検証結果

原文の20 facts、22引用と文字位置を照合。決定的検査18項目合格、独立AI検証12項目全てpass。完成記事と検証原稿は一致。

比較表6行は全て2資料以上に根拠がある。未知セル1件。表に「資料で確認できず」が含まれる場合だけ注記を付ける条件を確認した。

本文等と原文の最長連続一致16文字。これは表を除く検査であり、法的な権利保証ではない。

編集回数：1。初稿はwriter-original.json、編集内容はeditorial-revision.jsonに保存。

## API使用量と保存先

本文生成：gpt-4.1-mini-2025-04-14。独立検証：gpt-4.1-2025-04-14。API実行2回。入力20800 tokens、出力3052 tokens。推定料金 USD $0.0465712（税・為替換算を除く推定値）。

使用量、プロンプト、構造化スキーマ、要求・応答、表セルの根拠、照合記録は ../.local/comparison-article-c27-eighth-20261014/ に保存。APIキーと認証ヘッダーは保存していない。

既存API記事・比較報告書と元のC02/C24評価証跡309ファイルのSHA-256が不変。記事はローカルファイルに保存した。

2026年10月14日確認の[GPT-4.1 mini公式単価](https://developers.openai.com/api/docs/models/gpt-4.1-mini)と[GPT-4.1公式単価](https://developers.openai.com/api/docs/models/gpt-4.1)により推定。API利用条件は[Structured Outputs公式資料](https://developers.openai.com/api/docs/guides/structured-outputs)を参照。
