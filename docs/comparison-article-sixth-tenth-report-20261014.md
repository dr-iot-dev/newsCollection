# 第6〜第10候補の選定とOpenAI APIによる比較記事作成

作成日：2026年10月14日（日本時間）。

第1〜第5候補と重複しない5組を選び、各組3資料の原文に基づいて比較記事を作成した。順位は共通用途、比較工程、具体的な根拠と条件を原文照合して決めた編集上の順序であり、元のMMR順位や自動採用条件の合格を意味しない。元のneeds_review・ready判定・閾値は変更していない。

## 作成した記事

|候補|組と比較記事|F ID|最低類似度|独立AI検証|
|---|---|---|---:|---|
|第6候補 C03|[顧客対応AI3サービスの有人通話支援・問診とナレッジ活用の違い](comparison-article-c03-customer-support-20261014.md)|F010/F456/F932|0.660682|12/12 pass|
|第7候補 C17|[アプリ脆弱性診断3方式の自動化・専門家確認と改善工程の違い](comparison-article-c17-vulnerability-assessment-20261014.md)|F333/F411/F488|0.661661|12/12 pass|
|第8候補 C27|[AI映像監視3タイプの検知対象・警戒設定とイベント後の運用](comparison-article-c27-ai-surveillance-20261014.md)|F278/F711/F902|0.567349|12/12 pass|
|第9候補 C25|[AI搭載イヤホン3製品の通話・翻訳・録音整理とアプリ利用条件](comparison-article-c25-ai-earbuds-20261014.md)|F671/F870/F985|0.552600|12/12 pass|
|第10候補 C14|[製造業向けエッジAI支援3構成の基盤統合・運用と実装検討](comparison-article-c14-edge-ai-support-20261014.md)|F066/F138/F959|0.587076|12/12 pass|

## 第6候補：C03

対象：HARMONY Ver1.10／Navie／GeN。

顧客問い合わせ対応という共通の利用場面があり、有人通話の支援、問診型Web対話、既存Webマニュアル活用の違いを具体的に説明できる。

比較範囲：顧客問い合わせ対応をAIで支援する工程。オペレーターの通話支援とWeb上の自己解決を区別。

最低類似度0.6606817816640671、平均0.669309944571709。元の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。機械条件を通過させるための閾値変更やreadyへの書き換えは行っていない。

[個別の作成・検証記録](comparison-article-c03-sixth-creation-report-20261014.md)。比較表5行、未知セル1件。推定API料金 USD $0.0707984。

## 第7候補：C17

対象：セルバ AI脆弱性診断サービス／SynX 脆弱性診断サービス／AeyeScan Androidアプリ診断。

診断対象、AI・人の関与、報告と修正への接続が確認できる。セルバとSynXの委託支援とAeyeScanのAndroid向け追加機能を工程単位で比較できる。

比較範囲：企業のWeb・モバイルアプリ等の脆弱性を調べ、結果確認や改善へつなぐ工程。委託診断と自動診断ツールを区別。

最低類似度0.6616609516474751、平均0.6723836997761833。元の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。機械条件を通過させるための閾値変更やreadyへの書き換えは行っていない。

[個別の作成・検証記録](comparison-article-c17-seventh-creation-report-20261014.md)。比較表5行、未知セル0件。推定API料金 USD $0.0402464。

## 第8候補：C27

対象：AZx MF2A／TSD-4FMS-IPC／i-PRO Xシリーズ上位2機種。

人物・車両の検知、警戒設定、撮影方式、運用条件に違いがある。F278はMF2Aへ限定し、F902は自然言語検知の対象と明記されたXシリーズ上位2機種を1対象群として扱う。

比較範囲：施設・現場の映像監視で、検知対象の設定とイベント後の運用を比べる。固定式・デュアルレンズ・全方位を区別。

最低類似度0.567348531145726、平均0.6483172049717475。元の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。機械条件を通過させるための閾値変更やreadyへの書き換えは行っていない。

[個別の作成・検証記録](comparison-article-c27-eighth-creation-report-20261014.md)。比較表6行、未知セル1件。推定API料金 USD $0.0465712。

## 第9候補：C25

対象：UGREEN ClipBuds Pro2／EDIFIER Comfo Bass Pro／GLIDiC AI +u Buds。

イヤホンとアプリで音声を扱う共通場面があり、通話ノイズ低減、録音・翻訳、記録後の助言の違いを示せる。AIという名称だけで同じ機能と扱わない。

比較範囲：ワイヤレスイヤホンの音声利用とアプリ連携を比較。通話補助・翻訳・録音後の整理の目的を区別。

最低類似度0.5525999484500651、平均0.6166234715880589。元の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。機械条件を通過させるための閾値変更やreadyへの書き換えは行っていない。

[個別の作成・検証記録](comparison-article-c25-ninth-creation-report-20261014.md)。比較表6行、未知セル3件。推定API料金 USD $0.0412824。

## 第10候補：C14

対象：日立情報通信エンジニアリング エッジAIゲートウェイ統合／Idein・CTC Actcast＋D-Native構成／TED Try it! SLM on Edge。

製造業向けエッジ活用を共通とし、OT統合、分散デバイス運用とデータ分析、SLM評価から製品組込みの検討という支援段階の差を説明できる。

比較範囲：製造業が現場・製品のエッジ環境でデータやAIを活用する際の基盤・運用・評価支援を整理。

最低類似度0.5870762841581596、平均0.633198989913096。元の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。機械条件を通過させるための閾値変更やreadyへの書き換えは行っていない。

[個別の作成・検証記録](comparison-article-c14-tenth-creation-report-20261014.md)。比較表5行、未知セル1件。推定API料金 USD $0.0397404。

## 生成・照合・検証

5記事ともgpt-4.1-mini-2025-04-14で初稿を生成し、Codexが原文・引用と照合して1回編集した。生成直後の本文、入力パッケージ、当時の検査結果を別ファイルに保持している。本文作成と検証はOpenAI Responses API、構造化応答、store=False、出力上限7,000 tokens、ツールなしで実行した。

完成原稿は別モデルgpt-4.1-2025-04-14で12項目を検証し、全項目passを確認した。第6候補の初回検証は判定理由が空欄だったため最終判定に採用せず、説明を要求して1回だけ再検証した。再検証でも12項目全てpassとなり、全記事の各判定に非空の理由があることを確認した。初回応答と追加使用量も保存・集計した。

原文の103 facts、121引用と文字位置、15資料の入力ハッシュを照合した。最終記事は18項目の決定的検査に合格し、別モデルに送った検証原稿との一致も確認した。機械的検査・AI検証は法的な保証や現行仕様の確認を意味しない。

C27ではMF2Aの仕様へMP2Aを混在させず、i-PROは上位2機種という対象群に限定した。i-PRO全モデルのIP66は追加で原文照合し、対象群にも共通する値として表の未知セルを補正した。追加の上位耐環境等級は対象品番との対応が取れないため採用しない。

C25ではClipBuds Pro2の本文IP65と仕様欄IP56が不一致であるため、その比較値を除いた。再生時間・Talk AI・有料プラン・データ管理の説明も、それぞれの機能と製品に適用範囲を限定した。

未知欄の注記は表に「資料で確認できず」が含まれる場合だけ掲載する。第7候補C17は未知セルが0件のため、当該注記を掲載しない。他4記事は表の未知セルに応じて注記を掲載した。

## API使用量と料金

APIは執筆5回、検証6回（第6候補の再検証1回を含む）、合計11回。入力111881 tokens、出力13848 tokens。推定料金合計 USD $0.2386388。抽出・埋め込み・編集作業、税・為替換算は含めない。

料金は実使用量と2026年10月14日確認の[GPT-4.1 mini公式単価](https://developers.openai.com/api/docs/models/gpt-4.1-mini)、[GPT-4.1公式単価](https://developers.openai.com/api/docs/models/gpt-4.1)から計算した推定額である。APIの構造化応答は[公式資料](https://developers.openai.com/api/docs/guides/structured-outputs)を確認した。

## 保存した成果物

完成記事と個別報告書はdocsへ保存した。入力原文、引用・文字位置、表セル根拠、API要求・応答、実行モデル・使用量、初稿、編集内容、検証結果は .local/comparison-article-c03-sixth-20261014/、comparison-article-c17-seventh-20261014/、comparison-article-c27-eighth-20261014/、comparison-article-c25-ninth-20261014/、comparison-article-c14-tenth-20261014/ に保持する。APIキーや認証ヘッダーは記録していない。

全体の選定・編集・最終監査は .local/comparison-article-sixth-tenth-20261014/ に保存した。既存の第1〜第5候補の記事・証跡・比較報告書と、今回参照した元評価の309ファイルは事前SHA-256と一致し、変更がない。記事はローカルファイルに保存した。
