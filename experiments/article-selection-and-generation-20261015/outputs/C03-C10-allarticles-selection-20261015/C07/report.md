# C07：全13記事の選定結果

GPT-4.1の判定：NO_SET。以下の確認はこのチャットのアシスタントによるもので、別モデルの検証結果ではない。

第一候補：なし
記事ID：なし

確認結果：モデルが選定不可と判定。

予備候補：なし
記事ID：なし

確認結果：なし。

## 本文照合の観察

モデルは選定不可。用途の分散に加え、F809とF876はほぼ同じ内容と判定。

このクラスターではモデルが候補を返さなかった。モデルの全組み合わせに対する不存在判断を、独立した全件審査で立証したものではない。候補が返らなかった4クラスターは原資料全文と判定原文を保存し、上の理由はモデルの説明を要約した。

## 入力記事

| 重心順位 | 記事ID | 記事名 |
| --- | --- | --- |
| 1 | F184 | [NTTドコモビジネスとPowder Keg Technologies、AIを活用しOT環境の資産可視化から攻撃リスクの検証までを自動化するシステムを開発](https://prtimes.jp/main/html/rd/p/000000015.000148445.html) |
| 2 | F663 | [フォトシンス、凸版印刷、トライバル、顔認証入退室管理ソリューション「ピッコネ®」を開発](https://prtimes.jp/main/html/rd/p/000000089.000011385.html) |
| 3 | F809 | [Web3ベースプラットフォーム創造に向けた成果の報告（第一弾）](https://prtimes.jp/main/html/rd/p/000000015.000109020.html) |
| 4 | F876 | [Web3ベースプラットフォーム創造に向けた成果の報告（第一弾）](https://prtimes.jp/main/html/rd/p/000000075.000025296.html) |
| 5 | F732 | [AI異常予兆検知ソリューション「@DeAnoS」にSaaS版を追加](https://prtimes.jp/main/html/rd/p/000000331.000023654.html) |
| 6 | F034 | [自律走行ロボットとAIで設備点検をDX化](https://prtimes.jp/main/html/rd/p/000000620.000032702.html) |
| 7 | F329 | [ペンタセキュリティ、ファイル暗号化ソリューション「D.AMO KE」 Linux版の機能拡張](https://prtimes.jp/main/html/rd/p/000000115.000032363.html) |
| 8 | F387 | [OKI、生成AIを活用した次世代コンタクトセンターシステムの新商品「CTstage AIコンシェルジュ」を開発](https://prtimes.jp/main/html/rd/p/000000910.000017036.html) |
| 9 | F516 | [NTTドコモビジネスのセキュリティ統合型ネットワークサービス「docomo business RINK®」におけるWANセキュリティのふるまい検知に網屋の「ALog」を提供](https://prtimes.jp/main/html/rd/p/000000221.000027033.html) |
| 10 | F632 | [削孔管理IoTシステム「削孔Palette」が国土交通省NETISに登録](https://prtimes.jp/main/html/rd/p/000000049.000045691.html) |
| 11 | F697 | [クラウド管理型ネットワーク「KOKOMO」シリーズに新モデル追加](https://prtimes.jp/main/html/rd/p/000000166.000002807.html) |
| 12 | F460 | [PTC、Fisica Applied Technologiesが製品開発基盤としてCreoおよびWindchillを採用したと発表](https://prtimes.jp/main/html/rd/p/000000052.000099939.html) |
| 13 | F997 | [TOPPAN、コンテンツの来歴情報を付与、確認する技術がC2PAの適合製品（Conforming Product）に認定](https://prtimes.jp/main/html/rd/p/000001973.000033034.html) |

## 記録

- [モデルの選定結果原文](selection-result.md)
- [入力記事の全文と段落番号](input-articles.json)
- [実際に使用した指示](selection-prompt.txt)
- [モデル名・トークン数](selection-execution.json)
- [機械可読結果](summary.json)

この記事選択実験では比較記事を生成していない。「有望」は入力候補としての見込みであり、G1〜G6を満たす完成記事として検証済みという意味ではない。
