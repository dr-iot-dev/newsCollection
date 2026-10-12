# 語句検索に使える共通比較軸の抽出

実施日：2026-10-12。Discoveryと、AIを使わない検索語の整理・一致判定を対象とする。

## 現行の方針

- 同分野の製品・サービス間で一般的に比較する性質・機能・仕様・提供条件を軸にする。
- 軸名は24文字以内の短い名詞句とし、括弧、例示、商品名、セット名、長い修飾を外す。
- 温度監視セットと設備監視セットの価格は「価格」へまとめる。
- 機械的に分割しない。一般的な独立機能名のない細目は、トリガーや拡張機能などの共通名へまとめる。
- LTEやKNXなどの方式・規格の値は軸名ではなく、「通信方式」「対応規格」などの検索語にする。
- 件数の目標・上限は設けない。記事固有の細目で件数を増やさない。

## AIを使わない検索

各軸はlabel、question、search_terms、関連段落を持つ。検索に使うのはlabelとsearch_termsで、説明用のquestionを検索式にしない。検索はこれらの語のOR一致。NFKC正規化・大小文字の統一を行い、英字では単語境界を確認する。正規表現や指示をモデルに自由生成させず、通常の文字列一致だけを使う。

検索語は原文の関連段落に出現する語を残す。数値付きの細目、文章、広すぎる説明語を除き、認識できた記事固有の社名を含む語も除く。例えば、ソフトウェア更新に対する「更新」だけの検索や、外部連携に対する「警報」だけの検索は除く。

今回の3〜5記事群では、軸名または適切な検索語が2記事以上に出現する軸を共通候補として残す。この条件は文字列の出現であり、比較値が2製品から抽出できたという判定ではない。Extraction後の過半数条件とも別である。

```python
from app.core.comparison_dynamic_axes import matching_axis_terms

matches = matching_axis_terms(article_text, candidates.axes)
# {axis_id: (一致した語, ...)}。AIへの呼出はない。
```

## IoTでの出力

同じ保存済み記事を使い、gpt-5.2でDiscoveryを再実行した。最終の生成は各群1回。その出力へコードによる検索語整理と共有記事条件を適用した。値抽出・選定・AI検証・記事生成は実行していない。

| 記事群 | LLMの候補 | 検索語整理後の共通候補 |
| --- | ---: | ---: |
| A・B・C・D・E | 20 | 10 |
| A・B・D | 18 | 7 |

| 資料 | 内容 |
| --- | --- |
| A | [ラトック：温度・設備監視](https://prtimes.jp/main/html/rd/p/000000385.000023921.html) |
| B | [Roosterコネクト：ルータ・接続機器の監視](https://prtimes.jp/main/html/rd/p/000000020.000087711.html) |
| C | [Nobest-Tag：設備台帳・点検管理](https://prtimes.jp/main/html/rd/p/000000003.000125126.html) |
| D | [obniz Now：建物設備の監視・制御](https://prtimes.jp/main/html/rd/p/000000099.000040376.html) |
| E | [BizStack Workflow：現場業務の自動化](https://prtimes.jp/main/html/rd/p/000000250.000035514.html) |

### 5記事群

| 軸名 | 検索語 | 一致記事 |
| --- | --- | --- |
| クラウド監視 | クラウド／クラウド監視・制御／クラウドへ送信 | A・B・D |
| 遠隔監視 | 遠隔監視／遠隔から確認 | A・B・D |
| 通知 | 通知／メール／アラート通知 | A・B・E |
| 可視化 | 可視化／グラフ表示 | B・E |
| データ保存 | 自動記録／記録／データ保存期間 | A・D・E |
| 遠隔管理 | リモート一括管理／設定ファイル配信／遠隔ソフトウェア書き換え | B・D |
| 外部連携 | 連携／外部情報 | A・B・C・D・E |
| 自動化 | 自動化／自動制御 | D・E |
| 監視対象データ | 温度データ／設備データ／センサーデータ | A・B・D・E |
| 価格 | 期間限定価格／通常価格／お見積もり | A・D |

[全候補の定義・引用・一致語・除外軸](../.local/dynamic-axis-iot-20261012/discovery-searchable-release-normalized/iot5.json)
[元のDiscovery出力・モデル履歴](../.local/dynamic-axis-iot-20261012/discovery-searchable-release/iot5.json)

### 3記事群

| 軸名 | 検索語 | 一致記事 |
| --- | --- | --- |
| 価格 | 期間限定価格／通常価格／価格／お見積もり | A・D |
| 遠隔監視 | 遠隔監視／クラウド監視 | A・B・D |
| 通知 | 通知／メール／アラート通知 | A・B |
| データ記録 | 自動記録／ログ／挙動の記録 | A・B・D |
| クラウド連携 | クラウドへ送信／クラウド監視／クラウドと直結 | A・B・D |
| 通信方式 | LTE／Wi-Fi／電波強度 | A・B |
| 遠隔制御 | 監視・制御／遠隔制御 | B・D |

[全候補の定義・引用・一致語・除外軸](../.local/dynamic-axis-iot-20261012/discovery-searchable-release-normalized/monitoring3.json)
[元のDiscovery出力・モデル履歴](../.local/dynamic-axis-iot-20261012/discovery-searchable-release/monitoring3.json)

## 実行方法

比較項目だけを抽出するモードを追加した。Discoveryのモデルを設定すれば実行でき、値抽出や独立検証のモデル設定は不要。

```powershell
news-weave comparison-axes discover --discovery-only --item ARTICLE_UUID_1 --item ARTICLE_UUID_2 --item ARTICLE_UUID_3 --output .local/axes-discovery --call-budget 2
```

candidates.jsonに項目定義・検索語・根拠を、axis-search.jsonに記事別の一致語を保存する。audit.jsonとai-runs.jsonも保存する。終了状態はcandidates_ready。--discovery-onlyを省く場合は従来の値抽出・選定・独立検証までを実行する。

## 検証と限界

関連テスト41件通過・33件skip（今回のPostgreSQL用環境変数は未設定）。検索語の表記違い・大小文字・英字境界、括弧付き軸名、広すぎる語、数値付き細目、原文にない語、単一記事限定の候補、会社名付き語の除去、Discovery単独終了と再開を確認した。ruff・mypy（121ソース）通過。

同じ入力記事への一致は処理の動作確認であり、別の記事群での検索精度を評価した結果ではない。語句一致は当該項目の記載を探す手掛かりで、提供機能・条件の確定ではない。語の多義性による過検出や未収録の表記による未検出は残りうる。例えば、5記事群の「データ保存」と3記事群の「データ記録」のように、群ごとの名称の揺れはまだある。
