# 全30クラスタへのMMR順位表の拡張

計算日：2026年10月14日。保存済みベクトル・帰属確率・感度分析だけを利用。OpenAI API、ローカルLLM推論、埋め込みAPIの追加呼び出しは0回。

## 対象と代表組の決め方

未掲載のC07・C08・C11・C12・C15・C20・C23・C28・C29・C30を追加した。各3記事組を固定グループGとして組内メドイドを選び、前回と同じMMR式・重みでスコアを求めた。各クラスタ全所属記事から作る全3記事組、合計8,836組・1,969ペアを計算した。

主表は、既存の第1〜第20候補の組とスコアを保持し、未掲載10クラスタから最高スコアの組を1組ずつ加えた30組の拡張順位である。既存20組のスコアや元候補番号は変更していない。

既存組は編集選定、新規組は全組合せ中の最大という代表組の選択条件の違いがある。このため、全30クラスタを同じ条件で比べる「各クラスタの数値最大組」の順位も別表に併記する。主表は前回の順位表の拡張、別表は全クラスタの統一条件による数値比較である。

このスコアには比較適性、原文の情報量、同一製品や同一発表の重複除外、12項目検証を加えていない。新規組は比較記事作成・原文照合・独立検証を行った組ではない。数値最大の組に同一対象や用途不一致が含まれる可能性も残し、元の自動判定理由を下に示す。採用候補や第21〜第30候補と命名したものではない。

C07の数値最大組はF809とF876を含む。原文では同じジャスミー・パナソニック アドバンストテクノロジーの協業成果を各社が配信した記事であり、異なる3製品の比較候補としては不適切である。今回の順位はこれを除外しない純粋な数値順として明示し、重複確認を別段階に置く必要性を示す例として扱う。

## 拡張順位：既存20組＋未掲載10クラスタ

|順位|クラスタ|元候補・区分|テーマ|MMRスコア|3記事|
|---:|---|---|---|---:|---|
|1|C07|数値最大組・重複発表あり・追加|IT基盤・運用|0.948581|F663/F809/F876|
|2|C10|元第1候補|[ロボット掃除機](comparison-article-c10-robot-vacuums-20261014.md)|0.938725|F677/F698/F950|
|3|C18|元第20候補|[コンテンツ制作・確認](comparison-article-c18-content-workflows-20261014.md)|0.915670|F095/F267/F413|
|4|C30|数値最大組・追加|医療業務・関連AI|0.910366|F600/F780/F844|
|5|C17|元第7候補|[脆弱性診断](comparison-article-c17-vulnerability-assessment-20261014.md)|0.908970|F333/F411/F488|
|6|C12|数値最大組・追加|健康・見守り|0.907146|F291/F443/F579|
|7|C11|数値最大組・追加|企業業務AI・データ活用|0.906987|F371/F459/F552|
|8|C15|数値最大組・追加|IT・ネットワーク管理|0.904439|F069/F097/F231|
|9|C25|元第9候補|[AIイヤホン](comparison-article-c25-ai-earbuds-20261014.md)|0.903375|F671/F870/F985|
|10|C05|元第19候補|[水インフラ監視](comparison-article-c05-water-monitoring-20261014.md)|0.902822|F170/F302/F445|
|11|C06|元第17候補|[外観検査](comparison-article-c06-visual-inspection-20261014.md)|0.901868|F176/F627/F651|
|12|C03|元第6候補|[顧客対応支援](comparison-article-c03-customer-support-20261014.md)|0.899611|F010/F456/F932|
|13|C23|数値最大組・追加|住宅IoT|0.899194|F308/F599/F930|
|14|C27|元第8候補|[AI映像監視](comparison-article-c27-ai-surveillance-20261014.md)|0.890777|F278/F711/F902|
|15|C02|元第5候補|[設備稼働監視](comparison-article-c02-equipment-monitoring-20261014.md)|0.889367|F007/F039/F234|
|16|C01|元第11候補|[IoTルータ・ゲートウェイ](comparison-article-c01-iot-gateways-20261014.md)|0.886775|F006/F042/F289|
|17|C22|元第3候補|[AI面接](comparison-article-c22-ai-interviews-20261014.md)|0.883132|F673/F831/F903|
|18|C09|元第18候補|[画像による現場判断](comparison-article-c09-image-monitoring-20261014.md)|0.871156|F046/F071/F685|
|19|C13|元第2候補|[不動産情報入力](comparison-article-c13-property-entry-20261014.md)|0.866235|F065/F438/F637|
|20|C04|元第12候補|[セキュリティ運用](comparison-article-c04-security-operations-20261014.md)|0.856658|F017/F140/F303|
|21|C24|元第4候補|[帳票入力](comparison-article-c24-document-entry-20261014.md)|0.845022|F181/F408/F428|
|22|C20|数値最大組・追加|農業・地域サービス|0.834992|F126/F848/F949|
|23|C21|元第14候補|[企業のAI導入](comparison-article-c21-ai-implementation-20261014.md)|0.816389|F133/F156/F463|
|24|C19|元第15候補|[企業研修・学習](comparison-article-c19-ai-learning-20261014.md)|0.813758|F412/F708/F951|
|25|C29|数値最大組・追加|業務文書・企画|0.810767|F441/F563/F725|
|26|C08|数値最大組・追加|小売・企業業務基盤|0.806249|F038/F110/F429|
|27|C26|元第16候補|[IoT開発ボード](comparison-article-c26-iot-development-boards-20261014.md)|0.798584|F198/F213/F601|
|28|C16|元第13候補|[会議録音・議事録](comparison-article-c16-meeting-records-20261014.md)|0.788250|F332/F634/F868|
|29|C28|数値最大組・追加|AI連携・業務ツール|0.777586|F310/F344/F587|
|30|C14|元第10候補|[エッジAI導入支援](comparison-article-c14-edge-ai-support-20261014.md)|0.755472|F066/F138/F959|

## 追加10クラスタの代表記事と元評価

### C07：拡張順位1位、スコア0.948581

組内メドイド：F809。最低ペア類似度：0.624082。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。

原文確認による注意：F809/F876は同じ協業成果の別社配信。3つの独立した比較対象ではない。

- F663 [フォトシンス、凸版印刷、トライバル、顔認証入退室管理ソリューション「ピッコネ®」を開発](https://prtimes.jp/main/html/rd/p/000000089.000011385.html)（株式会社Photosynth）

- F809 [Web3ベースプラットフォーム創造に向けた成果の報告（第一弾）](https://prtimes.jp/main/html/rd/p/000000015.000109020.html)（パナソニック アドバンストテクノロジー株式会社）

- F876 [Web3ベースプラットフォーム創造に向けた成果の報告（第一弾）](https://prtimes.jp/main/html/rd/p/000000075.000025296.html)（ジャスミー株式会社）

### C30：拡張順位4位、スコア0.910366

組内メドイド：F600。最低ペア類似度：0.570608。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。

- F600 [『Apollo AI』が医療法人永井病院で大きな業務改革を実現──電子カルテ MI・RA・Is（株式会社シーエスアイ） × AIエージェントの、生成AI活用の基幹システム](https://prtimes.jp/main/html/rd/p/000000012.000169742.html)（株式会社Albatrus）

- F780 [PreMed、医療機関向けAIネイティブ予約システム「Galapagos」を自社開発。患者はLINEトークだけで予約が完結し、管理画面の細かな設定までAIエージェントで実行](https://prtimes.jp/main/html/rd/p/000000002.000183085.html)（PreMed株式会社）

- F844 [シェアメディカル、医療AIを安全に実行するための「医療AIハーネス」MediLine Engineを発表](https://prtimes.jp/main/html/rd/p/000000040.000016841.html)（株式会社シェアメディカル）

### C12：拡張順位6位、スコア0.907146

組内メドイド：F291。最低ペア類似度：0.645192。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。

- F291 [イオングループの健康サービス「からサポ」開発をWellmiraとネオスが支援](https://prtimes.jp/main/html/rd/p/000000018.000182591.html)（テクミラホールディングス株式会社）

- F443 [【北海道大発スタートアップ】仮想センサ最新モデル「MIRUWS® M4」登場！PDS機能でウェルネスデータの安全な共有と行動変容をスマートに実現](https://prtimes.jp/main/html/rd/p/000000034.000057464.html)（株式会社　ミルウス）

- F579 [「東京マラソン2027」にてWWS（Workout Well-being Scorer）を提供](https://prtimes.jp/main/html/rd/p/000000001.000192047.html)（株式会社ネットウエルシステム）

### C11：拡張順位7位、スコア0.906987

組内メドイド：F552。最低ペア類似度：0.626574。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。

- F371 [リーガルテック社 × AIデータ社、製造業を再編成](https://prtimes.jp/main/html/rd/p/000000357.000042056.html)（リーガルテック株式会社）

- F459 [ファインズの「AIOナビ」に新機能『AIOメディアブリッジ』](https://prtimes.jp/main/html/rd/p/000000052.000034396.html)（株式会社ファインズ）

- F552 [顧問契約時代のAI経営参謀、AI孔明 on IDXの税理士向け「AI Tax Loop on IDX」によるAI Executive PMOが税理士事務所の生産性を最大化](https://prtimes.jp/main/html/rd/p/000000821.000040956.html)（AIデータ株式会社）

### C15：拡張順位8位、スコア0.904439

組内メドイド：F231。最低ペア類似度：0.616191。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。

- F069 [Netskope、SASEとSSEの両分野において、 継続的なリーダーシップが評価される](https://prtimes.jp/main/html/rd/p/000000055.000137550.html)（Netskope Japan株式会社）

- F097 [NinjaOne、従業員が利用するブラウザの可視化・制御を実現するNinjaOne Browser Management」を発表](https://prtimes.jp/main/html/rd/p/000000003.000184948.html)（NinjaOne, LLC）

- F231 [NetApp、企業の「どこでも、あらゆるものを構築する」力を最大化](https://prtimes.jp/main/html/rd/p/000000190.000047898.html)（ネットアップ合同会社）

### C23：拡張順位13位、スコア0.899194

組内メドイド：F308。最低ペア類似度：0.600392。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。

- F308 [長谷工コーポレーションとLiveSmartが新機能を共同開発](https://prtimes.jp/main/html/rd/p/000000055.000031331.html)（株式会社LiveSmart）

- F599 [株式会社Gハウス、“全棟スマートホーム化”。注文住宅にホームIoTを標準搭載し、快適・安心な未来の暮らしを実現](https://prtimes.jp/main/html/rd/p/000000012.000159579.html)（株式会社Gハウス）

- F930 [南部建設が実現する、相場より1万円高くても1カ月で満室のスマートホーム戦略](https://prtimes.jp/main/html/rd/p/000000162.000033770.html)（株式会社アクセルラボ）

### C20：拡張順位22位、スコア0.834992

組内メドイド：F126。最低ペア類似度：0.617597。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。

- F126 [Landport横浜杉田にスマートコミュニティ農園「”Vegestic Farm” Yokohama Sugita by grow」がいよいよオープン！](https://prtimes.jp/main/html/rd/p/000000067.000035570.html)（プランティオ株式会社）

- F848 [【FOOMA JAPAN 2026】株式会社NEXTAGE、次世代わさび栽培モジュールに国内外から多数の反響](https://prtimes.jp/main/html/rd/p/000000042.000063114.html)（株式会社NEXTAGE）

- F949 [都市農をゲーム感覚で楽しもう！リアル連動型ソーシャルAI栽培アプリ「grow β」をプランティオ社・アイティフォー社と共同開発](https://prtimes.jp/main/html/rd/p/000000247.000019796.html)（株式会社アイフリーク モバイル）

### C29：拡張順位25位、スコア0.810767

組内メドイド：F441。最低ペア類似度：0.523020。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、similarity_below_threshold、insufficient_comparison_axes、no_meaningful_difference。

- F441 [生成AIから“業務共創型AI”へ 企画業務の0→10を支援する“Nomatica 2.0“へ](https://prtimes.jp/main/html/rd/p/000000032.000113498.html)（株式会社博報堂テクノロジーズ）

- F563 [AaaS、オーケストレーションAIによりメディアプラニングを高度化 次世代型メディアプラニング支援ソリューション「AaaS AI Planner」を実装](https://prtimes.jp/main/html/rd/p/000001234.000008062.html)（株式会社博報堂）

- F725 [朝日奈央さんが再びナレッジ発掘現場へ！今度はマニュアル制作に大苦戦！？NotePM 新CM「埋蔵ナレッジ～進まない現場～」篇](https://prtimes.jp/main/html/rd/p/000000263.000032205.html)（トヨクモ株式会社）

### C08：拡張順位26位、スコア0.806249

組内メドイド：F038。最低ペア類似度：0.394578。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、similarity_below_threshold、insufficient_comparison_axes、no_meaningful_difference。

- F038 [Hanshow-AI搭載プラットフォーム「xPilot」を正式リリースデータ活用からリアルタイム実行へ--小売店舗DXの新たなステージへ](https://prtimes.jp/main/html/rd/p/000000006.000180931.html)（Hanshow Japan株式会社）

- F110 [「e-Stand」によるデータ利活用構想の実現に向けて](https://prtimes.jp/main/html/rd/p/000000015.000117600.html)（株式会社ネクストフィールド）

- F429 [Vusionの革新的ソリューション、『Vusionプラットフォーム』『スマート電子棚札』をベルギーの小売企業「Extra Shop」が採用。](https://prtimes.jp/main/html/rd/p/000000023.000126241.html)（VusionGroup株式会社）

### C28：拡張順位29位、スコア0.777586

組内メドイド：F344。最低ペア類似度：0.588591。元の自動採用条件：不採用・保留。理由：needs_review、unconfirmed_shared_purpose、insufficient_comparison_axes、no_meaningful_difference。

- F310 [ハートコア、AI検索対策サービス「HeartCore LuLuMO」のリリースを発表](https://prtimes.jp/main/html/rd/p/000000057.000068468.html)（ハートコア株式会社）

- F344 [モルフォ、3D再構成技術『Morpho Photogrammetry Toolkit™』を発表](https://prtimes.jp/main/html/rd/p/000000154.000064140.html)（株式会社モルフォ）

- F587 [B-Roca、モランボン株式会社の社内生成AIチャットボット「モランチャット」を開発](https://prtimes.jp/main/html/rd/p/000000005.000172359.html)（株式会社B-Roca）

## 統一条件の別表：全30クラスタから各数値最大組を選ぶ

この表では既存20クラスタについても全組合せから最大を取り直した。組が変わったクラスタでは既存の完成記事と対応しない。数値最大化だけによる代表組で、比較記事としての採用を意味しない。

|順位|クラスタ|元候補・区分|テーマ|MMRスコア|3記事|
|---:|---|---|---|---:|---|
|1|C07|数値最大組・重複発表あり・追加|IT基盤・運用|0.948581|F663/F809/F876|
|2|C19|数値最大組|企業研修・学習|0.941559|F708/F722/F835|
|3|C27|数値最大組|AI映像監視|0.939420|F206/F260/F287|
|4|C10|数値最大組|[ロボット掃除機](comparison-article-c10-robot-vacuums-20261014.md)|0.938725|F677/F698/F950|
|5|C22|数値最大組|AI面接|0.924053|F675/F730/F903|
|6|C18|数値最大組|コンテンツ制作・確認|0.920804|F095/F267/F509|
|7|C17|数値最大組|脆弱性診断|0.920498|F253/F538/F541|
|8|C01|数値最大組|IoTルータ・ゲートウェイ|0.919817|F312/F955/F965|
|9|C03|数値最大組|顧客対応支援|0.919626|F010/F282/F456|
|10|C05|数値最大組|水インフラ監視|0.917619|F302/F425/F427|
|11|C04|数値最大組|セキュリティ運用|0.915271|F054/F134/F303|
|12|C02|数値最大組|設備稼働監視|0.915101|F118/F234/F301|
|13|C09|数値最大組|画像による現場判断|0.913697|F046/F048/F071|
|14|C21|数値最大組|企業のAI導入|0.913094|F463/F606/F625|
|15|C30|数値最大組・追加|医療業務・関連AI|0.910366|F600/F780/F844|
|16|C12|数値最大組・追加|健康・見守り|0.907146|F291/F443/F579|
|17|C11|数値最大組・追加|企業業務AI・データ活用|0.906987|F371/F459/F552|
|18|C13|数値最大組|不動産情報入力|0.906729|F438/F608/F908|
|19|C26|数値最大組|IoT開発ボード|0.906325|F213/F525/F610|
|20|C15|数値最大組・追加|IT・ネットワーク管理|0.904439|F069/F097/F231|
|21|C25|数値最大組|[AIイヤホン](comparison-article-c25-ai-earbuds-20261014.md)|0.903375|F671/F870/F985|
|22|C06|数値最大組|[外観検査](comparison-article-c06-visual-inspection-20261014.md)|0.901868|F176/F627/F651|
|23|C23|数値最大組・追加|住宅IoT|0.899194|F308/F599/F930|
|24|C24|数値最大組|帳票入力|0.864813|F181/F428/F519|
|25|C20|数値最大組・追加|農業・地域サービス|0.834992|F126/F848/F949|
|26|C29|数値最大組・追加|業務文書・企画|0.810767|F441/F563/F725|
|27|C08|数値最大組・追加|小売・企業業務基盤|0.806249|F038/F110/F429|
|28|C16|数値最大組|[会議録音・議事録](comparison-article-c16-meeting-records-20261014.md)|0.788250|F332/F634/F868|
|29|C28|数値最大組・追加|AI連携・業務ツール|0.777586|F310/F344/F587|
|30|C14|数値最大組|エッジAI導入支援|0.761798|F066/F091/F138|

## 計算方法と検証

式と値は前回と同じ。u=(1+s)/2、R(i)=0.70u(i,m)+0.15p(i)+0.15A(i,m)、MMR(i｜S)=0.75R(i)−0.25max[u(i,j),j∈S]。残り2記事の追加順を両方試し、MMR合計の大きい方を組のTスコアにする。

メドイドはその3記事の平均コサインが最大の記事。メドイド同点は帰属確率、公開日時の降順、F ID昇順。順位同点は1e-12の許容差で判定し、最低類似度、平均類似度の降順、F ID列の辞書順とする。表は丸め前の値で順位を決め、小数6桁で表示した。

8,836スコア・1,969コサインを未正規化ベクトルから別式で再計算した。最大コサイン差3.3306690738754696e-16、最大スコア差4.440892098500626e-16。代表30組×2表の入力順6通りと、各クラスタの候補の前順・逆順で最大組が同じになることを検証した。既存20組のスコア・メドイドも一致した。

保存済みの665記事を使ったクラスタ結果に固定し、ID非統合の新方針による666記事と混ぜていない。今後PR TIMES企業IDを統合しない実装・選択結果は変更していない。異なるクラスタ間のpは相対的な所属度で、比較記事の共通品質尺度ではない点も前回どおりである。

## 保存ファイル

- [拡張順位CSV](../.local/comparison-mmr-ranking-all-clusters-20261014/expanded-ranking.csv)／[詳細JSON](../.local/comparison-mmr-ranking-all-clusters-20261014/expanded-ranking.json)

- [統一条件順位CSV](../.local/comparison-mmr-ranking-all-clusters-20261014/uniform-cluster-max-ranking.csv)／[詳細JSON](../.local/comparison-mmr-ranking-all-clusters-20261014/uniform-cluster-max-ranking.json)

- [全8,836組CSV](../.local/comparison-mmr-ranking-all-clusters-20261014/all-triplet-scores.csv)／[全組JSON](../.local/comparison-mmr-ranking-all-clusters-20261014/all-triplet-scores.json)

- [入力・条件](../.local/comparison-mmr-ranking-all-clusters-20261014/input-manifest.json)／[検証結果](../.local/comparison-mmr-ranking-all-clusters-20261014/validation.json)／[計算スクリプト](../.local/comparison-mmr-ranking-all-clusters-20261014/calculate.py)

- [C07重複発表の原文確認記録](../.local/comparison-mmr-ranking-all-clusters-20261014/source-identity-observation.json)

- [前回の20組順位と拡張表](comparison-mmr-ranking-twenty-20261014.md)
