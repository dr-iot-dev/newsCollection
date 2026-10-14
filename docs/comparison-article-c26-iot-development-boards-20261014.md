# IoT開発ボードの通信・拡張接続と試作環境の違い

IoT機器の試作基盤として、MicroCat.1、XIAO nRF54LM20A Sense、MCX向けFRDM開発ボード群を取り上げる。通信の組み込み方、既存の拡張資産、開発環境を比較の軸とする。LTEを備えるマイコンボード、センサー付き近距離無線ボード、複数MCUに対応する開発ボード群という対象範囲を保ち、発表資料から確認できる構成を整理する。

## 比較表

| 項目 | MicroCat.1（[資料1](https://prtimes.jp/main/html/rd/p/000000031.000023719.html)） | XIAO nRF54LM20A Sense（[資料2](https://prtimes.jp/main/html/rd/p/000000065.000140089.html)） | MCX向けFRDM開発ボード群（[資料3](https://prtimes.jp/main/html/rd/p/000000013.000149856.html)） |
| --- | --- | --- | --- |
| 対象と構成 | Pico 2互換LTEマイコンボード | 近距離無線・IMU・マイク搭載Sense | MCX向けFRDM開発ボード群 |
| 通信の説明 | LTE Cat.1 bis | SoCがBluetooth LE・Thread・Zigbee・Matter等に対応 | 資料で確認できず |
| 拡張接続 | Pico 2互換GPIO、nanoSIM、USB-C | GPIO28本、USB-C、NFC、外部アンテナ、XIAO拡張 | MCU I/Oの標準ヘッダ |
| 開発環境 | PPP搭載MicroPython | nRF Connect SDK、Zephyr RTOS、PlatformIO | MCUXpresso、VSCode/Eclipse、IAR・Keil |
| 試作に使う資産 | Pico用拡張基板・サンプルコード | 拡張ボード、アクセサリ、チュートリアル、サンプル | MCU-Link、ドライバ・ミドルウェア・サンプル |

各提供元の保存済み発表資料に基づき、対象範囲と導入・運用工程を整理した。IoT・組み込み機器の試作で使う開発ボードの通信、拡張接続、開発環境の比較。「資料で確認できず」は非対応を意味しない。

同一条件で効果・精度・費用を測定した比較ではない。提供時期・仕様・料金は発表資料の記載であり、2026年10月14日時点の現行仕様・契約価格を確認したものではない。

## 比較の考察

通信を含む試作の出発点が異なる。メカトラックスのMicroCat.1は、RP2350Bを採用したRaspberry Pi Pico 2互換ボードにLTE Cat.1 bisを組み込む構成である。Seeed StudioのXIAO nRF54LM20A Senseは、NordicのSoCと電源管理ICに、6軸IMUとデジタルマイクを加えた構成で、音声や動きを利用する試作を支える。Farnellの発表は、NXPのMCXシリーズとFRDM開発ボード群の取り扱い追加を説明する。FRDM欄は単一型番の仕様を表していない。 [資料1](https://prtimes.jp/main/html/rd/p/000000031.000023719.html) [資料2](https://prtimes.jp/main/html/rd/p/000000065.000140089.html) [資料3](https://prtimes.jp/main/html/rd/p/000000013.000149856.html)

通信方式の説明では、MicroCat.1は公衆LTE網へ接続する構成、XIAO SenseはSoCがBluetooth LE、Thread、Zigbee、Matterなどに対応する構成となる。XIAOの各規格への対応説明から、全規格を同時に使用できるとは判断しない。MCXはシリーズによって特徴が異なるため、無線対応や一部シリーズのNPUをFRDM全体の共通仕様に置き換えることもできない。必要な通信や処理の条件は、採用するボードの型番ごとに整理する必要がある。 [資料1](https://prtimes.jp/main/html/rd/p/000000031.000023719.html) [資料2](https://prtimes.jp/main/html/rd/p/000000065.000140089.html) [資料3](https://prtimes.jp/main/html/rd/p/000000013.000149856.html)

外部機器との接続には、それぞれの拡張資産が使われる。MicroCat.1はPico 2互換のピン配置を持ち、既存のPico用拡張基板やMicroPythonのサンプルコードを活用できる。XIAO SenseはGPIO、USB-C、NFC、外部アンテナインターフェースを備え、XIAOの拡張ボードやアクセサリも利用できるとSeeed側は説明する。FRDM群はMCUの入出力へアクセスする標準ヘッダを備える。いずれも拡張を支えるが、接続資産の名前を互換性の保証として読み替えることはできない。 [資料1](https://prtimes.jp/main/html/rd/p/000000031.000023719.html) [資料2](https://prtimes.jp/main/html/rd/p/000000065.000140089.html) [資料3](https://prtimes.jp/main/html/rd/p/000000013.000149856.html)

開発環境では、MicroCat.1がPPPを組み込んだMicroPythonを用意し、ATコマンドの知識なしでLTE通信のコードを実装できると説明している。XIAO SenseはnRF Connect SDK、Zephyr RTOS、PlatformIOをサポートする。FRDM群はMCUXpressoの環境で、Visual Studio Code向けツールやEclipseベースのIDE、IAR、Keilを選択でき、ドライバ、ミドルウェア、サンプルも提供される。通信コードから始める構成と、組み込み向けツール群を選ぶ構成の違いが見える。 [資料1](https://prtimes.jp/main/html/rd/p/000000031.000023719.html) [資料2](https://prtimes.jp/main/html/rd/p/000000065.000140089.html) [資料3](https://prtimes.jp/main/html/rd/p/000000013.000149856.html)

電源やデバッグの組み込み方も確認点となる。XIAO SenseのnPM1300は充電、電圧調整、電源管理、残量測定をまとめたICである。FRDM群の説明にはMCU-LinkデバッグプローブとUSB-Cケーブルが含まれる。一方、MicroCat.1の発表は、拡張メモリとMicroPython環境を用意したセルラー開発基盤としての構成を示す。これらは別の設計上の要素であり、同じ消費電力や開発時間を測った結果ではない。試作で使う通信、センサー、拡張基板とツールを分けて確認する比較となる。 [資料1](https://prtimes.jp/main/html/rd/p/000000031.000023719.html) [資料2](https://prtimes.jp/main/html/rd/p/000000065.000140089.html) [資料3](https://prtimes.jp/main/html/rd/p/000000013.000149856.html)

## 出典

- 資料1: [MicroPythonでLTE通信、ラズパイPico 2互換ボード「MicroCat.1」を13,500円で発売](https://prtimes.jp/main/html/rd/p/000000031.000023719.html)（発表日：2026-07-02）

- 資料2: [Nordicを採用したSeeed Studioのワイヤレス開発ボード「XIAO nRF54LM20A Sense」と「XIAO nRF54LM20A」が、高性能と優れた電源管理を実現](https://prtimes.jp/main/html/rd/p/000000065.000140089.html)（発表日：2026-10-08）

- 資料3: [ファーネル、革新的なNXP®半導体マイクロコントローラとFRDM開発ボードをポートフォリオに追加](https://prtimes.jp/main/html/rd/p/000000013.000149856.html)（発表日：2025-05-07）

## 使用したAIモデル

- 本文作成：gpt-4.1-mini-2025-04-14（OpenAI API）
- 独立検証：gpt-4.1-2025-04-14（OpenAI API）
