# Extraction：103語除外・AI／IoT限定の実記事結果

実施日：2026-10-13。除外語を58語から103語へ増やし、記事の分野をAIまたはIoTに限定した。一般ニュースリリース一覧を使用せず、AI／IoT検索の一覧と、タイトル・本文冒頭による分野判定を通過した記事だけをDB検索の対象とする。[Extraction仕様](extraction-word-count-spec-20261012.md)。

| 項目 | 結果 |
| --- | --- |
| 判定済みの異なる記事 | 1707件 |
| タイトル語で除外 | 1404件 |
| AI／IoTの記載がないため除外 | 103件 |
| 除外合計 | 1507件 |
| 検索・集計対象 | 200件。既定の最低200件を満たす |
| AIのみ / IoTのみ / 両方 | 140件 / 37件 / 23件 |
| 本文保存済み | 501件。過去の除外記事の原文を含む |
| 除外記事のうち本文を保存していないもの | 1206件 |
| Discovery候補 | 以前生成した50候補。同じ語彙ハッシュ |
| 一致候補数 / 一致ゼロ | 1〜21 / 0件 |
| Extractionの検索方法 | 保存済みDBへのSQL検索・COUNT(DISTINCT) |
| 今回のAI呼出 | 0回 |

タイトル除外は指定語の部分一致。「本」は日本・本格等にも一致し、「入会」の重複を1語にまとめた。AI／IoTの語はタイトルまたは本文冒頭1,200文字で確認し、会社概要などの見出し以降を判定に含めない。記事の各分野と判定語はcounts.jsonに保存した。AI／IoTの両方に該当する記事も総件数では1記事。

## 確認用の表とDB

- [対象200件の記事・分野・カウント・含んでいる語](../.local/extraction-word-count-20261012/counts.md)：[CSV](../.local/extraction-word-count-20261012/counts.csv)、[JSON](../.local/extraction-word-count-20261012/counts.json)。
- [除外1507件と理由](../.local/extraction-word-count-20261012/excluded-articles.md)：[CSV](../.local/extraction-word-count-20261012/excluded-articles.csv)、[JSON](../.local/extraction-word-count-20261012/excluded-articles.json)。
- [判定済み全記事](../.local/extraction-word-count-20261012/title-review.md)、[分野判定記録](../.local/extraction-word-count-20261012/domain-screenings.json)。
- [記事・除外フラグ・分野フラグ・語彙のSQLite DB](../.local/extraction-word-count-20261012/iot-articles.sqlite)。DB名とcorpus IDは以前のIoT実行から継続しているが、現在の内容はAI／IoT限定。
- [概要](../.local/extraction-word-count-20261012/summary.json)、[全行の照合結果](../.local/extraction-word-count-20261012/title-filter-validation.json)、[取得履歴](../.local/extraction-word-count-20261012/collection-progress.json)。

## 再実行

```powershell
news-weave extraction count --database .local/extraction-word-count-20261012/iot-articles.sqlite --corpus iot-20261012 --vocabulary .local/extraction-word-count-20261012/vocabulary.json --output .local/extraction-word-count-20261012/recount
```

最低件数200を緩和せずに実行した。除外フラグ、分野フラグと現方針版で対象をSQLから選び、除外記事を候補語の検索関数へ渡す前に外す。各対象記事の保存済みタイトル・本文から分野、候補ID、一致語を再照合し、全行の数と一覧の一致を確認した。除外IDは検索結果に0件。

## 履歴

最初の220件の除外前はbefore-title-filter/、58語で45件へ絞った時点はafter-title-filter-220/、58語で200件へ補充した結果はbefore-expanded-filter-20261013/に保管した。現在の結果はルートのcounts.*を参照する。

語彙は以前、ユーザー承認後に公開実記事5件をOpenAI gpt-5.2へ送信して生成した50候補。今回の追加取得・分野判定・ExtractionにはAI呼出を使用していない。Discoveryの実行記録・監査は変更していない。
