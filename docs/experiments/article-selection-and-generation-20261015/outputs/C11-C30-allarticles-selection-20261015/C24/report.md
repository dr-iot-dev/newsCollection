# C24：全7記事の選定結果

モデルの返答：TWO_SETS。原文内のstatus：TWO_SETS。

本チャットによる確認：両組とも比較対象・処理環境の整理が必要。

## 第一候補

- F408：[【テクノツリー】帳票電子化ツール「XC-Gate」にてAI-OCR機能をリリース](https://prtimes.jp/main/html/rd/p/000000007.000129803.html)
- F519：[エッジAI‐OCR「i-Repo EdgeOCR」に「四角定型（YotsukaD AI）モード」を追加。 ラベルをAIが自動認識し、位置合わせ不要で定型読み取りが可能に。](https://prtimes.jp/main/html/rd/p/000000231.000074154.html)
- F181：[紙帳票の「転記作業ゼロ。」へ。現場帳票AI「paper-base」、複数帳票のExcel一覧出力に対応](https://prtimes.jp/main/html/rd/p/000000008.000171615.html)

条件整理が必要。現場でカメラから値を電子帳票へ入力するOCRと、紙・PDF帳票を後からデータ化するサービスで入力元・処理工程が異なる。

## 予備候補

- F408：[【テクノツリー】帳票電子化ツール「XC-Gate」にてAI-OCR機能をリリース](https://prtimes.jp/main/html/rd/p/000000007.000129803.html)
- F519：[エッジAI‐OCR「i-Repo EdgeOCR」に「四角定型（YotsukaD AI）モード」を追加。 ラベルをAIが自動認識し、位置合わせ不要で定型読み取りが可能に。](https://prtimes.jp/main/html/rd/p/000000231.000074154.html)
- F428：[OCR結果を、社内エクセル形式へそのままインポートできる画期的な新機能「EXCELA」がGenX AI OCRで利用可能に！](https://prtimes.jp/main/html/rd/p/000000022.000165900.html)

条件整理が必要。Excel帳票を電子化する機能と、OCR結果を既存Excelテンプレートへ出力する機能を同じExcel連携として評価しない。

## 本文照合で確認した点

- XC-Gateはカメラの映像から文字・数値を読み取って電子帳票へ反映し、i-Repo EdgeOCRはラベル等の文字を現場帳票へ取り込む。paper-baseは紙・PDF等のデータ化とExcel出力である。現場の転記削減という接点はあるが、同じ作業を代替できる読取対象に絞る必要がある。 根拠：F408:P006, F408:P007, F519:P001, F519:P009, F181:P001, F181:P002。
- GenX EXCELAはOCR結果を既存のxlsxへ値だけ差し込む機能である。Excelを入力画面にする方式と、既存帳票へ出力する方式を同じ意味の比較軸にしない。 根拠：F428:P001, F428:P003, F428:P011。
- XC-Gateの本文はオンプレミス版の出荷とクラウド版の12月以降の予定を分けて記載する。モデル表のオンプレミス・クラウド併記には提供時期の注記が必要。 根拠：F408:P001, F408:P002。

## 入力記事

| 重心順位 | 記事ID | 記事名 |
| --- | --- | --- |
| 1 | F408 | [【テクノツリー】帳票電子化ツール「XC-Gate」にてAI-OCR機能をリリース](https://prtimes.jp/main/html/rd/p/000000007.000129803.html) |
| 2 | F519 | [エッジAI‐OCR「i-Repo EdgeOCR」に「四角定型（YotsukaD AI）モード」を追加。 ラベルをAIが自動認識し、位置合わせ不要で定型読み取りが可能に。](https://prtimes.jp/main/html/rd/p/000000231.000074154.html) |
| 3 | F428 | [OCR結果を、社内エクセル形式へそのままインポートできる画期的な新機能「EXCELA」がGenX AI OCRで利用可能に！](https://prtimes.jp/main/html/rd/p/000000022.000165900.html) |
| 4 | F209 | [【経理部門の皆様へ】キーボード入力不要の経理処理を実現！仕訳入力、データ確認、帳表作成、さらに給与計算や年末調整もこの１台で。経理PC「JDL Benny AI Station EX」新登場！](https://prtimes.jp/main/html/rd/p/000000061.000087577.html) |
| 5 | F181 | [紙帳票の「転記作業ゼロ。」へ。現場帳票AI「paper-base」、複数帳票のExcel一覧出力に対応](https://prtimes.jp/main/html/rd/p/000000008.000171615.html) |
| 6 | F358 | [AI活用を促進し、業務変革を加速するイメージスキャナー4機種を同時発売](https://prtimes.jp/main/html/rd/p/000000238.000053253.html) |
| 7 | F820 | [【iXacs ✕ 音声認識】スマートウォッチへの音声入力で作業内容の入力が可能になりました。](https://prtimes.jp/main/html/rd/p/000000023.000048806.html) |

## 記録

- [選定モデルの返答原文](selection-result.md)
- [入力記事の全文・段落番号](input-articles.json)
- [実際に使用した指示](selection-prompt.txt)
- [モデル名・トークン数・実行時間](selection-execution.json)
- [結果JSON](summary.json)

本文照合はこのチャットによる主要な用途・提供段階・重複・根拠の確認であり、別モデルによる検証ではない。「有望」は入力候補としての見込みで、G1〜G6を満たす完成記事の合格ではない。今回、比較記事は生成していない。
