# 組織ごとの最新記事によるクラスタリング

実施日：2026-10-13。状態：完了。

> 2026-10-14方針変更：今後は同じ公式社名でもPR TIMES企業IDを統合せず、IDごとに最新1件を選ぶ。以下の665記事・日立ID統合は旧方針で実施した履歴であり、再実行には新方針を使う。変更内容と差分は[評価基準の改善検討](comparison-selection-improvement-review-20261014.md)を参照。既存クラスタと第1〜第20候補のラベル・評価は遡って変更しない。

## 対象と最新記事の選択

対象は[既存の記事群F 1,000件](../.local/extraction-1000-20261013/embeddings/article-values.json)。AI／IoT、公式種類「商品サービス」、タイトル除外111語、一致候補数5以上の条件は引き継ぐ。この1,000件内で配信元組織ごとに最新記事を1件選び、残った665件を再クラスタリングした。対象外の記事を追加収集して1,000件に補充する処理は行わない。

組織はPR TIMESの配信元企業IDを基準とする。記事URLの企業IDを同じ公式HTMLの企業リンクで確認し、JSON-LDのNewsArticle.author（Organization）から公式組織名、datePublishedから公開日時を取得した。組織名はNFKC・casefold・連続空白の正規化のみを行い、同じ公式組織名の別企業IDも同一組織として統合する。今回この統合は「株式会社 日立製作所」の企業ID 67590・152541の1例だけだった。親会社・子会社や似た社名を推測で統合しない。

最新判定は公開日時をUTCに揃えて比較し、dateModifiedを使わない。タイムゾーンのない日本語サイトのdatePublishedは日本時間（UTC+09:00）として扱う。日時が完全一致する場合は数値のリリース番号が大きい記事、その後URL降順で決定する。全1,000件で公式組織・日時を確認済み。確認できない記事を推測の日時で選択しない。

元のF ID・記事URL・本文入力ハッシュ・1,536次元ベクトルを保持する。再採番・再埋め込みは行わず、ベクトルは元の値と完全一致する。335件をこのクラスタリング対象から除いた結果を別に保存し、元の記事DBと1,000件のベクトルは保持する。

## 結果

| 項目 | 結果 |
| --- | ---: |
| 選択前の記事群F | 1,000記事 |
| 公式配信元企業ID | 666 |
| 統合後の組織数 | 665 |
| 複数記事があった組織 | 135 |
| 選択した最新記事 | 665記事 |
| 同じ組織の旧記事等を除外 | 335記事 |
| HDBSCANクラスタ | 30 |
| クラスタ所属の記事 | 327記事 |
| ノイズ | 338記事 |
| 高密度コア | 67記事 |
| 確率上位候補／重心上位候補 | 各90記事 |
| 今回の埋め込みAPI呼び出し | 0 |
| 追加の埋め込みAPI料金 | 0米ドル |

日立製作所はF482（2026-09-16 11:00:02 日本時間）を採用した。全組織の採用記事と除外記事には公開日時、公式組織名、選択された記事IDを記録する。

## クラスタリング条件

前回と同じ条件を固定して実行した。

- 全665ベクトルをL2正規化。
- UMAP：cosine、15次元、n_neighbors=15、min_dist=0、random_state=42、n_jobs=1。
- HDBSCAN：縮約空間のeuclidean、min_cluster_size=5、min_samples=5、leaf。
- 各クラスタで帰属確率0.9以上の上位3件と、元の1,536次元重心に近い上位3件の共通部分をコアにする。同確率なら重心類似度で並べる。
- ノイズはコアに含めない。元空間の重心・ペア類似度を保存する。
- シード7・21、10・20次元、近傍30、最小クラスタ8の6通りで安定性を確認する。

| 条件変更 | クラスタ | ノイズ | コア | 主解析とのARI |
| --- | ---: | ---: | ---: | ---: |
| シード7 | 33 | 310 | 79 | 0.4943 |
| シード21 | 25 | 318 | 50 | 0.5653 |
| 10次元 | 29 | 313 | 60 | 0.5942 |
| 20次元 | 32 | 285 | 73 | 0.5228 |
| 近傍30 | 26 | 329 | 51 | 0.5511 |
| 最小クラスタ8 | 21 | 349 | 51 | 0.7976 |

組織の重複をなくすことは、同じ発表元による類似した記事の偏りを抑えるための条件。帰属確率や密度コアは意味的な正解率・純度を保証するものではない。今回の結果を確認するため、組織名・公開日時・元記事リンクと、元空間の類似度・条件変更時の安定性を表の詳細画面に表示する。

## 再実行

今後この条件でクラスタリングする場合は、最新組織記事を選ぶオプションと公式HTMLの取得監査DBを指定する。

```powershell
news-weave extraction cores --vectors .local/extraction-1000-20261013/embeddings/article-values.json --output .local/extraction-organization-latest-20261013/cores --latest-per-organization --audit-database .local/extraction-1000-20261013/collection-audit.sqlite
```

このコマンドはoutput/selectionへ選択済み入力と採用・除外記録を保存してからクラスタリングする。組織ごとの最新フィルタが記録された入力に組織の重複があれば、クラスタリング前にエラーとする。今回の実行では選択結果を下記selectionディレクトリに保存してから、保存済み入力に対して同じcores処理を実行した。

## 保存ファイルと検証

- [確認表HTML](../.local/extraction-organization-latest-20261013/cores/cores.html)。組織名でも検索でき、タイトルをクリックすると組織名・日本時間の公開日時を確認できる。
- [採用した665記事CSV](../.local/extraction-organization-latest-20261013/selection/organization-selected.csv)／[除外した335記事CSV](../.local/extraction-organization-latest-20261013/selection/organization-excluded.csv)。
- [組織・日時の公式メタデータ全1,000件](../.local/extraction-organization-latest-20261013/selection/organization-metadata.json)／[選択方針と実件数](../.local/extraction-organization-latest-20261013/selection/organization-selection.json)。公式HTMLのSHA-256と取得日時も記録する。
- [選択済み665ベクトル](../.local/extraction-organization-latest-20261013/selection/article-values.json)。
- [コア67件CSV](../.local/extraction-organization-latest-20261013/cores/cores.csv)／[全665記事の分類CSV](../.local/extraction-organization-latest-20261013/cores/article-clusters.csv)。
- [実データの検証結果](../.local/extraction-organization-latest-20261013/validation.json)。

選択後の組織一意性、全組織で公開日時が最大の記事であること、全665ベクトル・入力ハッシュの元データとの完全一致、元ファイルのSHA-256不変を独立に照合した。全665記事の分類の網羅性、元空間の重心・コサイン類似度、コアの共通部分、CSV行数も照合済み。選択・メタデータ・クラスタの関連15テスト、Ruff、変更3モジュールのmypyが通過した。

ブラウザでは全665記事・コア67件の切替、組織名検索で日立製作所が1記事だけになること、詳細画面の組織名・公開日時を確認した。横方向のはみ出しは0。[完成画面](../.local/extraction-organization-latest-20261013/cores-preview.jpg)。
