# 検証済み比較記事5件の下書き送信

実施日: 2026-10-10（日本時間）。送信先: https://kunsen.net。投稿者: news-weaver / News Weaver（ID 2）。

5件とも異なる記事URLを3件ずつ参照し、決定的検査と独立AI検証の12項目すべてに合格した。本文作成はgpt-5.2、独立検証はgpt-4.1。比較表、番号付き出典、実際の使用モデル表示、1536×1024の独自アイキャッチ（gpt-image-1.5）を保存した。状態は全件draftで、匿名RESTから表示されないことを確認した。

| 区分 | 記事（WordPress編集リンク） | 検証 | 出典数 | アイキャッチID |
| --- | --- | --- | --- | --- |
| 生成AI | [業務AIの情報基盤設計と自律実行の置きどころ](https://kunsen.net/wp-admin/post.php?post=5663&action=edit) | 12/12合格 | 3 | 5669 |
| IoTプラットフォーム | [IoT運用プラットフォームの接続と現場DX視点](https://kunsen.net/wp-admin/post.php?post=5664&action=edit) | 12/12合格 | 3 | 5668 |
| IoTプラットフォーム | [現場DXとIoT運用のクラウド基盤像](https://kunsen.net/wp-admin/post.php?post=5665&action=edit) | 12/12合格 | 3 | 5672 |
| セキュリティ | [脆弱性診断支援の対象範囲と提供形態](https://kunsen.net/wp-admin/post.php?post=5666&action=edit) | 12/12合格 | 3 | 5673 |
| セキュリティ | [クラウド型サイバー対策の情報収集と脆弱性診断の設計軸](https://kunsen.net/wp-admin/post.php?post=5667&action=edit) | 12/12合格 | 3 | 5676 |

## 検証した項目

事実の裏付け、タイトル、文体・冗長性、同社従来品の扱い、他社製品との比較、比較条件、比較表、主張の帰属、出典リンク、利用条件、独自表現、個人情報の12項目。対象のない同社従来品は本文から省き、欠落を非対応と扱わない。

全体の品質チェックはruff・mypyが成功し、pytestは602件成功・3件skip。最終変更後の関連テストも80件成功・2件skip。新環境だけに生成AI・IoT・セキュリティのトピック分類と比較軸を追加し、設立日・サイト開設日を製品の日付へ誤分類しないよう検査を強化した。不合格原稿の改稿履歴と出典集合予約を保持した。

接続確認用の既存下書き5660は今回の5件に含めていない。追加候補の設備遠隔監視記事は価格適用条件の確認待ちとして未送信。既存の公開投稿176件は保持され、newsCollection側の.env・compose.yamlのSHA-256にも変更がない。

newsWeaveの収集元はPR TIMESの6トピックが承認済み、日経1件は未承認で停止のままである。実送信と検証IDの詳細はGit対象外の.local/requested-comparisons-20261010.jsonに保存した。

## 記事別の出典

### 業務AIの情報基盤設計と自律実行の置きどころ

- [資料1](https://prtimes.jp/main/html/rd/p/000000001.000191685.html)
- [資料2](https://prtimes.jp/main/html/rd/p/000000049.000164127.html)
- [資料3](https://prtimes.jp/main/html/rd/p/000000424.000018764.html)

### IoT運用プラットフォームの接続と現場DX視点

- [資料1](https://prtimes.jp/main/html/rd/p/000000141.000073834.html)
- [資料2](https://prtimes.jp/main/html/rd/p/000000047.000031640.html)
- [資料3](https://prtimes.jp/main/html/rd/p/000000018.000168691.html)

### 現場DXとIoT運用のクラウド基盤像

- [資料1](https://prtimes.jp/main/html/rd/p/000000047.000031640.html)
- [資料2](https://prtimes.jp/main/html/rd/p/000000141.000073834.html)
- [資料3](https://prtimes.jp/main/html/rd/p/000000074.000040376.html)

### 脆弱性診断支援の対象範囲と提供形態

- [資料1](https://prtimes.jp/main/html/rd/p/000000064.000156001.html)
- [資料2](https://prtimes.jp/main/html/rd/p/000000081.000091210.html)
- [資料3](https://prtimes.jp/main/html/rd/p/000000049.000124664.html)

### クラウド型サイバー対策の情報収集と脆弱性診断の設計軸

- [資料1](https://prtimes.jp/main/html/rd/p/000000029.000045761.html)
- [資料2](https://prtimes.jp/main/html/rd/p/000000049.000124664.html)
- [資料3](https://prtimes.jp/main/html/rd/p/000000081.000091210.html)

