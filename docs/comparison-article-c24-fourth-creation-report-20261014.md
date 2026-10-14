# 第4候補・C24比較記事の作成・検証記録

作成日：2026年10月14日。

記事：[現場情報の帳票入力を支援する3機能の読み取り・確認と反映工程](comparison-article-c24-document-entry-20261014.md)

## 選定と比較範囲

3社の発表で読み取り・入力先・設定・確認工程を確認でき、紙を使い続ける方式、現場で電子帳票へ記録する方式、既存Excelへ確定値を反映する方式の違いを示せる。C24の最高類似度組ではなく、業務への反映工程を比較しやすい組を原文から編集上選んだ。

対象：F181 paper-base、F408 XC-Gate AI-OCR機能、F428 GenX AI OCR／EXCELA。

現場の帳票・表示情報を読み取り、業務帳票へ反映する工程。紙を残す運用と電子帳票へ直接入力する運用を区別

元評価はneeds_reviewのまま保持した。最低類似度0.6028095888952354、平均0.6282620473692003。元の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。順位は既存の自動スコアの順位ではなく、原文の比較しやすさに基づく編集上の順序。

## 検証結果

原文の31 facts、33引用と文字位置を照合。決定的検査18項目合格、独立AI検証12項目全てpass。完成記事と検証原稿は一致。

比較表7行は全て2資料以上に根拠がある。未知セル2件。表に「資料で確認できず」が含まれる場合だけ注記を付ける条件を確認した。

本文等と原文の最長連続一致18文字。これは表を除く検査であり、法的な権利保証ではない。

編集回数：1。初稿はwriter-original.json、編集内容はeditorial-revision.jsonに保存。

## API使用量と保存先

本文生成：gpt-4.1-mini-2025-04-14。独立検証：gpt-4.1-2025-04-14。API実行2回。入力21057 tokens、出力2551 tokens。推定料金 USD $0.0440532（税・為替換算を除く推定値）。

使用量、プロンプト、構造化スキーマ、要求・応答、表セルの根拠、照合記録は ../.local/comparison-article-c24-fourth-20261014/ に保存。APIキーと認証ヘッダーは保存していない。

既存API記事・比較報告書と元のC02/C24評価証跡440ファイルのSHA-256が不変。記事はローカルファイルに保存した。

2026年10月14日確認の[GPT-4.1 mini公式単価](https://developers.openai.com/api/docs/models/gpt-4.1-mini)と[GPT-4.1公式単価](https://developers.openai.com/api/docs/models/gpt-4.1)により推定。API利用条件は[Structured Outputs公式資料](https://developers.openai.com/api/docs/guides/structured-outputs)を参照。
