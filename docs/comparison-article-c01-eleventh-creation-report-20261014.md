# 第11候補・C01比較記事の作成・検証記録

作成日：2026年10月14日。

記事：[産業用IoT通信機器3製品の設備接続・回線切替と遠隔運用の違い](comparison-article-c01-iot-gateways-20261014.md)

## 選定と比較範囲

3社のIoT向け通信機器で、LTE・Wi-Fi、現場側の入出力、位置情報、導入運用条件の根拠が確認できる。レガシー設備への有線接続、BLEセンサー収集、小型ゲートウェイの構成差を比較できる。

対象：F006 ST956、F042 iGS03MP、F289 iG350B。

現場の設備・センサーの情報を広域回線へつなぐ産業用ルータ・ゲートウェイの接続と運用条件

元評価はneeds_reviewのまま保持した。最低類似度0.5225720549641047、平均0.6027068147872302。元の保留理由：similarity_below_threshold、insufficient_comparison_axes。順位は既存の自動スコアの順位ではなく、原文の比較しやすさに基づく編集上の順序。

## 検証結果

原文の25 facts、26引用と文字位置を照合。決定的検査18項目合格、独立AI検証12項目全てpass。完成記事と検証原稿は一致。

比較表6行は全て2資料以上に根拠がある。未知セル1件。表に「資料で確認できず」が含まれる場合だけ注記を付ける条件を確認した。

本文等と原文の最長連続一致17文字。これは表を除く検査であり、法的な権利保証ではない。

編集回数：1。初稿はwriter-original.json、編集内容はeditorial-revision.jsonに保存。

## API使用量と保存先

本文生成：gpt-4.1-mini-2025-04-14。独立検証：gpt-4.1-2025-04-14。API実行2回。入力20082 tokens、出力2622 tokens。推定料金 USD $0.0422904（税・為替換算を除く推定値）。

使用量、プロンプト、構造化スキーマ、要求・応答、表セルの根拠、照合記録は ../.local/comparison-article-c01-eleventh-20261014/ に保存。APIキーと認証ヘッダーは保存していない。

既存API記事・比較報告書と元のC02/C24評価証跡476ファイルのSHA-256が不変。記事はローカルファイルに保存した。

2026年10月14日確認の[GPT-4.1 mini公式単価](https://developers.openai.com/api/docs/models/gpt-4.1-mini)と[GPT-4.1公式単価](https://developers.openai.com/api/docs/models/gpt-4.1)により推定。API利用条件は[Structured Outputs公式資料](https://developers.openai.com/api/docs/guides/structured-outputs)を参照。
