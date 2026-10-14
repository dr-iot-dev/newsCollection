# 第11〜第15候補の選定とOpenAI APIによる比較記事作成

作成日：2026年10月14日（日本時間）。

第1〜第10候補と重複しない5組を、保存済み評価結果と原文から選んで比較記事を作成した。順位は、共通の利用場面、比較工程、根拠と条件の具体性に基づく編集上の順序であり、元のMMR順位や自動採用条件の合格を意味しない。元の保留状態・ready判定・閾値は変更していない。

## 比較記事

|候補|記事|対象|F ID|最低類似度|
|---|---|---|---|---:|
|第11候補 C01|[産業用IoT通信機器3製品の設備接続・回線切替と遠隔運用の違い](comparison-article-c01-iot-gateways-20261014.md)|ST956／iGS03MP／iG350B|F006/F042/F289|0.522572|
|第12候補 C04|[セキュリティ運用AI3構成の文脈分析・対応起動と人の判断](comparison-article-c04-security-operations-20261014.md)|ServiceNow Agentic Incident Response／Zscaler Agentic SOC／Vectra AI次世代プラットフォーム|F017/F140/F303|0.675492|
|第13候補 C16|[会議音声の取得・議事録化と業務共有を支える3構成の役割](comparison-article-c16-meeting-records-20261014.md)|SecureMemoCloud Windowsアプリ（β）／Shure IntelliMix Bar Pro／MA-EYES AI議事録機能|F332/F634/F868|0.570980|
|第14候補 C21|[企業のAI導入3方式の内製・個別実装代行と月額伴走の範囲](comparison-article-c21-ai-implementation-20261014.md)|MatrixFlow／クラウドワークス AI実装伴走プラン／Zept 外部AI事業部|F133/F156/F463|0.606158|
|第15候補 C19|[企業研修3サービスのAI対話・プロコーチ伴走と振り返りの違い](comparison-article-c19-ai-learning-20261014.md)|FRACTAL 対話型シミュレーション／One Cue（HQ・NEWONE）／UMU AGL|F412/F708/F951|0.556467|

## 第11候補：C01

3社のIoT向け通信機器で、LTE・Wi-Fi、現場側の入出力、位置情報、導入運用条件の根拠が確認できる。レガシー設備への有線接続、BLEセンサー収集、小型ゲートウェイの構成差を比較できる。

比較範囲：現場の設備・センサーの情報を広域回線へつなぐ産業用ルータ・ゲートウェイの接続と運用条件。

最低類似度0.5225720549641047、平均0.6027068147872302。元評価の保留理由：similarity_below_threshold、insufficient_comparison_axes。不足を閾値変更やreadyへの書き換えで通過させていない。

[個別の作成・検証記録](comparison-article-c01-eleventh-creation-report-20261014.md)。比較表6行、未知セル1件。推定API料金 USD $0.0422904。

## 第12候補：C04

3社のセキュリティ運用支援で、文脈データの統合、AIによる調査・優先順位、対応の連携と人の役割が説明されている。ServiceNowは6構成全体からインシデント対応部分へ限定する。

比較範囲：セキュリティ担当者の調査・トリアージ・対応判断をAIで支援する構成の比較。

最低類似度0.6754915856112303、平均0.6847790919468096。元評価の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。不足を閾値変更やreadyへの書き換えで通過させていない。

[個別の作成・検証記録](comparison-article-c04-twelfth-creation-report-20261014.md)。比較表5行、未知セル0件。推定API料金 USD $0.0386804。

## 第13候補：C16

会議での音声取得、AI処理との接続、議事録や情報の利用・管理に関する説明がある。録音アプリ、会議室機器、ERP追加機能の担当工程を分けて比較できる。

比較範囲：会議音声の取得から文字起こし・議事録・業務への共有に至る工程を整える3構成。

最低類似度0.5709795633102148、平均0.6163864044975295。元評価の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。不足を閾値変更やreadyへの書き換えで通過させていない。

[個別の作成・検証記録](comparison-article-c16-thirteenth-creation-report-20261014.md)。比較表5行、未知セル0件。推定API料金 USD $0.0389628。

## 第14候補：C21

自分で予測AIを構築するノーコード基盤と、専門家へ設計実装を依頼するプラン、課題整理から定着までの月額伴走を、担当者の作業・成果物・料金単位で比較できる。

比較範囲：企業が業務へAIを導入する際の内製ツール利用・個別実装代行・継続伴走という方法の比較。

最低類似度0.6061584085770354、平均0.6762282668215579。元評価の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。不足を閾値変更やreadyへの書き換えで通過させていない。

[個別の作成・検証記録](comparison-article-c21-fourteenth-creation-report-20261014.md)。比較表5行、未知セル0件。推定API料金 USD $0.0371024。

## 第15候補：C19

研修を業務判断・行動へつなぐ目的があり、シミュレーションでの評価、研修後の人による伴走とAI分析、教材生成とAI問いかけの違いを説明できる。

比較範囲：企業研修の学習・実践・振り返りを支えるAI対話、プロコーチ伴走、学習情報可視化の比較。

最低類似度0.5564670775021476、平均0.5774807234078835。元評価の保留理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。不足を閾値変更やreadyへの書き換えで通過させていない。

[個別の作成・検証記録](comparison-article-c19-fifteenth-creation-report-20261014.md)。比較表5行、未知セル0件。推定API料金 USD $0.0378272。

## 生成・編集・検証

本文生成はgpt-4.1-mini-2025-04-14、独立検証はgpt-4.1-2025-04-14を使用した。OpenAI Responses APIの構造化応答、store=False、出力上限7,000 tokens、ツールなしで実行。5記事とも初稿を保持し、Codexが原文・根拠引用と照合して1回編集した後、別モデルで完成原稿を検証した。

完成記事は各18項目の決定的検査と12項目の独立AI検証に全て合格した。各検証の理由が空でないこと、保存した完成記事が検証に送信した原稿と一致することも確認した。再検証は0回。

原文の96 facts、119引用と文字位置、15資料の入力ハッシュを照合した。検査は意味のすべての正しさや権利の法的保証、現行仕様の確認を意味しない。記事は発表資料に基づく比較範囲・条件を明記している。

第11候補はST956／iGS03MP／iG350Bだけを対象とし、GNSS搭載の別型番・旧製品価格改定を混在させない。C01の最低類似度0.522572は元の閾値0.55未満であり、自動採用の合格とは扱わない。

第12候補はServiceNowの6構成全体からAgentic Incident Responseへ限定。AIスペシャリストというソフトウェアの機能と人の専門家を区別し、他社と同じ承認ルールを推定しない。

第13候補は会議室の入力機器、Windows録音アプリ、ERPの追加議事録機能という担当工程を区別。未記載の録音・共有機能を非対応と断定しない。

第14候補は予測AIのノーコード基盤と、生成AIを含む個別実装・継続伴走を同じ成果物としない。月額、開始価格、税区分、支援時間と作業範囲を分けて比較した。

第15候補はAI対話の疑似体験、プロコーチの研修後伴走、AIによる教材土台生成・問いかけ・学習情報の可視化を区別。対象層や研修段階の差を保ち、能力の客観的査定や行動改善の保証とは扱わない。

「資料で確認できず」は非対応を意味しない旨の注記は、表にその表記がある第11候補だけに掲載した。第12〜第15候補は表の未知セルが0件のため注記を掲載していない。

## API使用量・費用

APIは執筆5回と検証5回、合計10回。入力91642 tokens、出力13273 tokens。推定料金合計 USD $0.1948632。抽出、埋め込み、編集作業、税・為替換算は含めない。

料金は保存済みusageと2026年10月14日確認の[GPT-4.1 mini公式単価](https://developers.openai.com/api/docs/models/gpt-4.1-mini)、[GPT-4.1公式単価](https://developers.openai.com/api/docs/models/gpt-4.1)に基づく推定額。[構造化応答の公式資料](https://developers.openai.com/api/docs/guides/structured-outputs)も確認した。

## 保存先と既存成果物

完成記事と個別報告書はdocsへ保存した。入力、引用・文字位置、表セルの根拠、要求・応答、モデル・使用量、未修正初稿、編集内容、検証結果は各候補の .local/comparison-article-*-20261014/ に保持する。APIキーや認証ヘッダーは保存していない。

全体の選定・編集・最終監査は .local/comparison-article-eleventh-fifteenth-20261014/ に保存。既存の第1〜第10候補の記事・証跡・比較報告書と参照した元評価の476ファイルは事前SHA-256と一致し、変更がない。記事はローカルのMarkdownファイルへ保存した。
