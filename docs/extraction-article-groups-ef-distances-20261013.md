# 記事群E・F：埋め込み値と全ペア距離

実施日：2026-10-13。ユーザーの明示承認後にOpenAI埋め込みAPIで実記事126件のベクトル値と全7,875ペアの距離を計算した。

## 記事群と入力

記事群Eは、103語のタイトル除外とAI／IoT分野条件を適用してExtractionで集計した200記事。一致候補数が4以下の74記事をEから除き、一致候補数が5以上の126記事を記事群Fとする。E自体と元のDBは保持し、Fは別の解析成果物として保存する。

記事群Fの各記事にF001〜F126の短いIDを割り当てた。一致候補数の降順・元の記事ID順でIDを決め、タイトル・URL・分野・一致候補数・入力ハッシュを保存する。現在のDBから候補数を照合し、記事群Eの件数・ID・候補数が元の集計結果と異なる場合は停止する。

- [送信予定の全文入力](../.local/article-group-f-distances-20261013/embedding-input.json)
- [記事群F一覧](../.local/article-group-f-distances-20261013/group-F.json)
- [記事群Eの集計](../.local/extraction-word-count-20261012/counts.md)

## ベクトル値と距離

入力は保存済みタイトル、空行、本文全体を連結した文章。元の本文を要約・切捨てせず、最大6,000 UTF-8バイトの226区間に分割する。OpenAIのtext-embedding-3-smallで各区間を埋め込み、区間のUTF-8バイト数を重みとする加重平均をL2正規化して、各記事の1つのベクトル値とする。同じモデル・同じ入力ハッシュの区間値は再利用し、途中で失敗しても完了した区間を再送信しない。

距離は1 − コサイン類似度。自己ペアを除き、同じペアの逆順を重複させず、126×125÷2＝7,875ペアを計算する。数値の丸め前の距離で昇順に並べ、同距離なら左右の記事IDで順序を固定する。ベクトルが空・非有限・ゼロ、モデルや次元が異なる場合は結果を作らない。

API入力は1区間最大6,000バイト、1リクエスト最大16区間とする。[OpenAIの入力上限](https://developers.openai.com/api/reference/resources/embeddings/methods/create)である1入力8,192トークン・全入力合計300,000トークンを下回るバイト数で区切る。距離の選択は[公式の埋め込みガイド](https://developers.openai.com/api/docs/guides/embeddings)のコサイン類似度に合わせる。

## 出力する表と各記事の値

- pair-distances.html：全7,875ペア。順位・距離・記事A・記事Bの4列。タイトルは1行表示とし、マウスを置くと全文、クリックすると全文・元記事リンク・一致候補数・分野を表示する。50行ずつ表示し、タイトル・ID・分野で検索できる。
- pair-distances.csv：全ペアの距離、記事ID、全文タイトル、URL。距離の昇順。
- pair-distances.json：全ペアの数値と計算条件。
- article-values.json：各F記事のvalueフィールドに実際のベクトル配列を保存する。モデル・次元・入力ハッシュも記録する。
- article-values.sqlite：記事別のベクトル値、区間キャッシュ、API使用記録、全ペア距離を保存する。

## 実行手順

入力を確定するだけの実行はAPIを呼び出さない。

```powershell
news-weave extraction distances --database .local/extraction-word-count-20261012/iot-articles.sqlite --corpus iot-20261012 --counts .local/extraction-word-count-20261012/counts.json --output .local/article-group-f-distances-20261013 --model text-embedding-3-small --prepare-only
```

同じコマンドから--prepare-onlyを外すとベクトルと距離を計算する。今回の送信はユーザーの明示承認後に実行した。設定済みAI_API_KEYを利用し、キーを出力や成果物に保存しない。

記事群の境界（4以下／5以上）、正規化した値、全ペアの距離と安定した順序、キャッシュ再開、ゼロベクトル拒否、送信前の入力照合、返却インデックスの並替え、HTMLへの記事文字列の安全な挿入を確認する。関連テスト140件とRuff・変更4ファイルのmypyが通過。

## 実行結果と確認用の表

| 項目 | 結果 |
| --- | --- |
| 記事群E | 200記事 |
| Eから除外した一致候補数4以下の記事 | 74記事 |
| 記事群F | 126記事 |
| 各記事の値 | text-embedding-3-small・1,536次元の正規化ベクトル |
| 全ペア | 7,875組。自己ペア・逆順重複を除く |
| 距離の範囲 | 0.030653〜0.801295 |
| API実行 | 15リクエスト・226区間・374,012入力トークン |

- [省スペースの全ペア表](../.local/article-group-f-distances-20261013/pair-distances.html)。全文タイトル表示・検索・ページ送り付き。
- [先頭30組のMarkdown表](../.local/article-group-f-distances-20261013/nearest-pairs.md)、[全7,875組のCSV](../.local/article-group-f-distances-20261013/pair-distances.csv)。
- [各記事のベクトル値](../.local/article-group-f-distances-20261013/article-values.json)、[値と距離のSQLite DB](../.local/article-group-f-distances-20261013/article-values.sqlite)。
- [全距離のJSON](../.local/article-group-f-distances-20261013/pair-distances.json)、[全件の照合結果](../.local/article-group-f-distances-20261013/validation.json)。

全126ベクトルが1,536次元で長さ1であること、全7,875組が一度ずつ現れて距離昇順であること、CSV件数の一致を確認した。全ペアの距離を保存済みベクトルから別の式で再計算し、差は最大2.2e-16だった。
