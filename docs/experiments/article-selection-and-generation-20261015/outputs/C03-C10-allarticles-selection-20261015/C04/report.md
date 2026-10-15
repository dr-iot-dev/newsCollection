# C04：全19記事の選定結果

GPT-4.1の判定：TWO_SETS。以下の確認はこのチャットのアシスタントによるもので、別モデルの検証結果ではない。

第一候補：ServiceNow／Zscaler／Vectra AI：AI活用型セキュリティ基盤
記事ID：F017, F140, F303

確認結果：要再検討。製品群全体と個別のSOC・検知機能で比較範囲が異なり、提供予定機能の混在もある。

予備候補：ServiceNow／Zscaler／Cohesity：防御・復旧基盤
記事ID：F017, F140, F135

確認結果：今回の厳格なカテゴリ・目的基準では不適。防御・SOC運用とAI基盤のバックアップ・復旧という補完的な役割を混在させている。

## 本文照合の観察

- ServiceNow Autonomous Securityは6つの統合ソリューションを包含する。Zscaler Agentic SOC、Vectraの検知・調査支援と比較する場合、何を選ぶ読者なのか、ServiceNowのどの機能・単位を対象にするのかを固定する必要がある。 根拠：F017:P005, F017:P010, F017:P023, F017:P024, F140:P002, F140:P024, F140:P026, F303:P007, F303:P011, F303:P013。
- ServiceNowのTier 2 SOC AIスペシャリストなどは2026年12月提供予定と本文に明記される。モデルはこれらを現行の自動化機能として並べ、G6も合格にしている。提供中と予定を分けて記載する必要がある。 根拠：F017:P024, F017:P032, F140:P032。
- Cohesity Agent Resilienceの主目的はAIエージェントを支えるインフラと関連資源の保護・復旧であり、検知・ガバナンスだけでは解消できない復旧のギャップを埋めるものと説明される。SOC防御基盤に代わる同一目的の候補として扱うと役割がずれる。 根拠：F135:P004, F135:P013, F135:P022, F135:P023, F135:P024。
- Cohesityは一部顧客向け提供で一般提供は2026年末予定。自動化構想と個別の提供済み機能も分ける必要がある。 根拠：F135:P005, F135:P009, F135:P011, F135:P030, F135:P032。

## 入力記事

| 重心順位 | 記事ID | 記事名 |
| --- | --- | --- |
| 1 | F189 | [AIセキュリティのCoWorker、国内初の自律型動的マルウェア解析AIプラットフォーム「Blue Agent for マルウェア解析」を発表。AIが解析を進め、人は判断に集中](https://prtimes.jp/main/html/rd/p/000000019.000156001.html) |
| 2 | F068 | [複数のAIプラットフォームを横断し、エージェントのリスクを可視化・制御する「Citadel Radar for Agents」を発表](https://prtimes.jp/main/html/rd/p/000000053.000075720.html) |
| 3 | F017 | [ServiceNow、業界で最も包括的なセキュリティソリューションであるAutonomous Securityを発表](https://prtimes.jp/main/html/rd/p/000000215.000029239.html) |
| 4 | F135 | [Cohesity、AIエージェントを支えるインフラストラクチャを保護・復旧する「Cohesity Agent Resilience」を発表](https://prtimes.jp/main/html/rd/p/000000087.000072250.html) |
| 5 | F303 | [Vectra AI、攻撃者のAIを悪用した活動に対し、瞬時に検知・防御する次世代プラットフォームを発表](https://prtimes.jp/main/html/rd/p/000000045.000108014.html) |
| 6 | F140 | [ゼットスケーラー、AI主導の脅威を封じ込める「Zscaler Agentic SOC」を発表](https://prtimes.jp/main/html/rd/p/000000118.000055108.html) |
| 7 | F346 | [クラウドストライク、エンドポイントにおける優位性をソフトウェアサプライチェーン保護へ拡張](https://prtimes.jp/main/html/rd/p/000000177.000031049.html) |
| 8 | F054 | [Rapid7、脅威データを攻撃者への対抗力に変える 「Rapid7 Intelligence」を発表](https://prtimes.jp/main/html/rd/p/000000004.000147512.html) |
| 9 | F241 | [CData、AIと業務システムをつなぐ単一の統制基盤『Connect AI Gateway』をリリース](https://prtimes.jp/main/html/rd/p/000000314.000017545.html) |
| 10 | F134 | [プルーフポイント、AI時代に従来の防御が見逃す攻撃を阻止](https://prtimes.jp/main/html/rd/p/000000084.000073972.html) |
| 11 | F123 | [クラロティ、新機能「Visibility Orchestration（可視性オーケストレーション）」で資産の可視化と実用的なリスク削減策を最適化](https://prtimes.jp/main/html/rd/p/000000052.000107680.html) |
| 12 | F910 | [Cloudflare、「検索か、AI学習か」の二者択一を解消](https://prtimes.jp/main/html/rd/p/000000121.000061678.html) |
| 13 | F078 | [Datadog、AIエージェントに統合オブザーバビリティデータへの安全かつリアルタイムなアクセスを提供する「MCP Server」を発表](https://prtimes.jp/main/html/rd/p/000000105.000077474.html) |
| 14 | F129 | [GitLabがGitLab 19.4をリリース](https://prtimes.jp/main/html/rd/p/000000071.000056974.html) |
| 15 | F667 | [OrcaRouter、サイバーセキュリティ研究向けモデル「OrcaSAQ-2 Cyber 27B Uncensored」のGGUF](https://prtimes.jp/main/html/rd/p/000000101.000138449.html) |
| 16 | F130 | [AIを活用した要求ベースのテスト作成機能を搭載：ベクターの「VectorCAST 2026」](https://prtimes.jp/main/html/rd/p/000000072.000118698.html) |
| 17 | F196 | [レジデンシャルプロキシ候補を評価・可視化する脅威インテリジェンス機能を「Senda Nexus」に追加](https://prtimes.jp/main/html/rd/p/000000027.000089968.html) |
| 18 | F112 | [Varonis、かつてないデータ増加時代に対応する「データ ライフサイクル マネジメント(DLM)」を発表](https://prtimes.jp/main/html/rd/p/000000018.000168998.html) |
| 19 | F024 | [MathWorks、MATLAB および Simulink の Release 2026b を発表](https://prtimes.jp/main/html/rd/p/000000011.000147023.html) |

## 記録

- [モデルの選定結果原文](selection-result.md)
- [入力記事の全文と段落番号](input-articles.json)
- [実際に使用した指示](selection-prompt.txt)
- [モデル名・トークン数](selection-execution.json)
- [機械可読結果](summary.json)

この記事選択実験では比較記事を生成していない。「有望」は入力候補としての見込みであり、G1〜G6を満たす完成記事として検証済みという意味ではない。
