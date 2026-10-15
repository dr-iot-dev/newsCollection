# 記事選定・比較記事生成の実験記録（2026-10-15）

クラスターから比較に適した3記事組を選び、生成段階で比較の適否を再判定した実験の記録。入力本文、モデル指示、返答原文、実行条件、確認所見を保存する。

[処理の流れの図と文章](outputs/processing-flow-20261015/processing-flow.md)には、今回の実験の実施範囲と、現行アプリの生成・独立検証・1回修正の経路を分けて記載した。SVG・PNG・Mermaid形式の図を保存している。

## 最新の結果

[GPT 6.1 Solによる生成結果](outputs/promising-comparison-gpt61-sol-20261015/report.md)：前回と同じ7組・同じ生成指示で、2組の記事を生成、5組を不適と判定した。返却モデル名は全7件で`gpt-6.1-sol`、API statusは`completed`。モデルへの入力に、前回の生成記事・不適理由や他の組の応答は含めていない。

| 対象 | 最新の生成判定 |
| --- | --- |
| C03・予備 | APPROPRIATE |
| C10・本命 | APPROPRIATE |
| C13・本命 | INAPPROPRIATE |
| C17・本命 | INAPPROPRIATE |
| C22・本命 | INAPPROPRIATE |
| C22・予備 | INAPPROPRIATE |
| C27・予備 | INAPPROPRIATE |

[記事と不適理由の全文](outputs/promising-comparison-gpt61-sol-20261015/results-all.md)、[生成後の確認所見](outputs/promising-comparison-gpt61-sol-20261015/editorial-review.md)、[実行記録一覧](outputs/promising-comparison-gpt61-sol-20261015/summary.json)を参照。

以前に本チャットのアシスタントが範囲を限定して生成したC13は、最新の確認では比較単位・代替性の条件から不適判定を支持し、採用扱いを見直した。以前の記録は当時の結果として保存している。

## 保存した実験

| 記録 | 内容 |
| --- | --- |
| [C01・重心に近い7記事](outputs/C01-ai-selection-20261015/report.md) | 当初のk=7による選定・生成適否確認 |
| [C01・全13記事](outputs/C01-all13-selection-20261015/report.md) | 全記事を用いた選定 |
| [C02・全11記事](outputs/C02-all11-selection-20261015/report.md) | 全記事を用いた選定 |
| [C03〜C10](outputs/C03-C10-allarticles-selection-20261015/report.md) | 各クラスター全記事を用いた選定 |
| [C11〜C30](outputs/C11-C30-allarticles-selection-20261015/report.md) | 各クラスター全記事を用いた選定 |
| [アシスタント自身による生成](outputs/promising-comparison-articles-20261015/report.md) | 7組から3記事生成・4組不適。当時の記録 |
| [GPT 6.1 Solによる生成](outputs/promising-comparison-gpt61-sol-20261015/report.md) | 同じ7組から2記事生成・5組不適。最新の実行 |

記事選定には`gpt-4.1-2025-04-14`を使用した。選定指示、生成指示、比較基準G1〜G6は各記録から追跡できる。実験上の指示はここに保存しており、業務実装のモデル指示の正本はリポジトリの`app/prompts/`である。

## ファイル構成と再確認

- `outputs/`：ユーザー向けに保存した結果・入力スナップショット・実行記録。
- `work/`：実験に使用したPythonスクリプトと指示文。
- `archive-manifest.json`：保存ファイルの相対パス・サイズ・SHA-256。元作業フォルダーからの転送を照合するための記録。

保存原文とハッシュを維持するため、このディレクトリの`.gitattributes`でGitの改行自動変換を無効にしている。

このディレクトリを基準に、次のコマンドで最新生成の返答原文・モデル名・入力ハッシュ・参照整合性を再確認し、全文集を再構成できる。APIは呼ばない。

```powershell
python work/finalize_gpt61_sol.py
```

APIを実行するスクリプトは別コマンドで、呼び出すとAPI利用が発生する。再実行済みリクエストを無条件に繰り返さないための記録チェックがある。保存済み入力の作成元には元の共有フォルダーのDB・埋め込みスナップショットを参照するスクリプトも含む。元のローカル依存データや一時リクエストのすべてをここへ複製したものではない。

APIキー、`.env`、キャッシュ、実行時の一時フォルダーは保存対象に含めていない。絶対パスを含む出自情報は当時の実行場所を示す記録である。実験の採否は、実機・実サービスの検証や、独立した評価モデルの採点とは区別する。
