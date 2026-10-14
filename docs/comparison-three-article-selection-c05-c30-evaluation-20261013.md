# C05〜C30のローカル3記事選定評価

更新日時：2026-10-14T00:01:49.435975+09:00。処理状態：`complete`。

完了26/26クラスタ、265記事・1494ペア・6447組合せ。採用0クラスタ。OpenAI API・外部API・埋め込みAPIは0回。

C03・C04と同じローカルOllamaモデル（固定ダイジェスト）、ネイティブ入力形式と初期採用条件を使った。C05〜C30だけを処理し、クラスタごとの入力・判定・数値評価・検証・報告書を保存した。用途・比較項目の辞書は各分野に合わせて事前固定し、本文が支持する分類だけをモデルに出力させた。

## クラスタ別結果

| クラスタ・報告書 | 記事 | ペア | 組合せ | ready | 状態 | 最終採用 |
| --- | --- | --- | --- | --- | --- | --- |
| [C05](comparison-three-article-selection-c05-evaluation-20261013.md) | 12 | 66 | 220 | 0 | needs_review | なし |
| [C06](comparison-three-article-selection-c06-evaluation-20261013.md) | 8 | 28 | 56 | 0 | needs_review | なし |
| [C07](comparison-three-article-selection-c07-evaluation-20261013.md) | 13 | 78 | 286 | 0 | needs_review | なし |
| [C08](comparison-three-article-selection-c08-evaluation-20261013.md) | 5 | 10 | 10 | 0 | needs_review | なし |
| [C09](comparison-three-article-selection-c09-evaluation-20261013.md) | 5 | 10 | 10 | 0 | needs_review | なし |
| [C10](comparison-three-article-selection-c10-evaluation-20261013.md) | 12 | 66 | 220 | 0 | needs_review | なし |
| [C11](comparison-three-article-selection-c11-evaluation-20261013.md) | 15 | 105 | 455 | 0 | needs_review | なし |
| [C12](comparison-three-article-selection-c12-evaluation-20261013.md) | 12 | 66 | 220 | 0 | needs_review | なし |
| [C13](comparison-three-article-selection-c13-evaluation-20261013.md) | 9 | 36 | 84 | 0 | needs_review | なし |
| [C14](comparison-three-article-selection-c14-evaluation-20261013.md) | 5 | 10 | 10 | 0 | needs_review | なし |
| [C15](comparison-three-article-selection-c15-evaluation-20261013.md) | 5 | 10 | 10 | 0 | needs_review | なし |
| [C16](comparison-three-article-selection-c16-evaluation-20261013.md) | 6 | 15 | 20 | 0 | needs_review | なし |
| [C17](comparison-three-article-selection-c17-evaluation-20261013.md) | 13 | 78 | 286 | 0 | needs_review | なし |
| [C18](comparison-three-article-selection-c18-evaluation-20261013.md) | 14 | 91 | 364 | 0 | needs_review | なし |
| [C19](comparison-three-article-selection-c19-evaluation-20261013.md) | 26 | 325 | 2600 | 0 | needs_review | なし |
| [C20](comparison-three-article-selection-c20-evaluation-20261013.md) | 7 | 21 | 35 | 0 | needs_review | なし |
| [C21](comparison-three-article-selection-c21-evaluation-20261013.md) | 11 | 55 | 165 | 0 | needs_review | なし |
| [C22](comparison-three-article-selection-c22-evaluation-20261013.md) | 16 | 120 | 560 | 0 | needs_review | なし |
| [C23](comparison-three-article-selection-c23-evaluation-20261013.md) | 8 | 28 | 56 | 0 | needs_review | なし |
| [C24](comparison-three-article-selection-c24-evaluation-20261013.md) | 7 | 21 | 35 | 0 | needs_review | なし |
| [C25](comparison-three-article-selection-c25-evaluation-20261013.md) | 13 | 78 | 286 | 1 | needs_review | なし |
| [C26](comparison-three-article-selection-c26-evaluation-20261013.md) | 11 | 55 | 165 | 0 | needs_review | なし |
| [C27](comparison-three-article-selection-c27-evaluation-20261013.md) | 11 | 55 | 165 | 0 | needs_review | なし |
| [C28](comparison-three-article-selection-c28-evaluation-20261013.md) | 7 | 21 | 35 | 0 | needs_review | なし |
| [C29](comparison-three-article-selection-c29-evaluation-20261013.md) | 5 | 10 | 10 | 0 | needs_review | なし |
| [C30](comparison-three-article-selection-c30-evaluation-20261013.md) | 9 | 36 | 84 | 0 | needs_review | なし |

## 集計と解釈

状態別：`{'needs_review': 26}`。プロフィールreadyは1記事。

採用0組や保留の原因は個別報告書の構造化・用途・比較項目・類似度の各段階に記録した。判定不明を閾値やMMRの重み変更で通過させない。モデルの未確定・抽出不足を、元の記事に情報がないことや比較可能な3記事が存在しないことと同一視しない。

人の正解ラベルによる精度評価は未実施。共通のルール検証、原文引用の文字列照合、独立したコサイン再計算、実データ入力順の不変性は各報告書・検証JSONに記録した。固定辞書による分類の見落としと比較項目の意味の妥当性は残る制約。

## ローカル使用量

| 項目 | 完了クラスタ分 |
| --- | --- |
| ローカル推論要求 | 538 |
| 入力token | 1433677 |
| 出力token | 224011 |
| 推論要求時間合計（秒） | 6896.962 |
| OpenAI／外部／埋め込みAPI要求 | 0／0／0 |
| API料金（米ドル） | 0 |

GPU・電力等の費用は金額換算していない。処理途中・失敗の使用量はクラスタ別のlocal-runsに保持し、完了時に集計する。

C01〜C04の成果物不変検証：`unchanged`。

## 実行記録

- [batch-status.json](../.local/comparison-three-article-selection-c05-c30-local-20261013/batch-status.json)
- [cluster-config.json](../.local/comparison-three-article-selection-c05-c30-local-20261013/cluster-config.json)
- [local-runtime.json](../.local/comparison-three-article-selection-c05-c30-local-20261013/local-runtime.json)
- [rule-validation.json](../.local/comparison-three-article-selection-c05-c30-local-20261013/rule-validation.json)
- [prior-artifact-sha256.json](../.local/comparison-three-article-selection-c05-c30-local-20261013/prior-artifact-sha256.json)
- [run-batch.py](../.local/comparison-three-article-selection-c05-c30-local-20261013/run-batch.py)
- [run-local.py](../.local/comparison-three-article-selection-c05-c30-local-20261013/run-local.py)
- [selection-core.py](../.local/comparison-three-article-selection-c05-c30-local-20261013/selection-core.py)

全26クラスタの処理は完了。終了検証は [batch-validation.json](../.local/comparison-three-article-selection-c05-c30-local-20261013/batch-validation.json) に保存した。

## 最終照合の補足

プロフィール状態の全体集計：`{"multiple_targets": 233, "unknown": 31, "ready": 1}`。採用制御前のペア比較可能性：`{"unknown": 988, "yes": 236, "no": 270}`。

全538モデル要求の入力範囲・固定モデル・版・キャッシュキーを照合した。プロフィール要求では保存タイトル・本文全文との一致を、ペア要求では当該クラスタ内の記事だけを使用していることを確認した。保存引用は288項目を検証済み。モデルの意味判断の正しさとは区別する。

構造化修復には引用不一致だけでなく項目ID重複も含まれるため、個別報告書の修復件数の表記を補正した。追加の推論要求は0回。

[最終照合記録](../.local/comparison-three-article-selection-c05-c30-local-20261013/final-audit.json) / [照合スクリプト](../.local/comparison-three-article-selection-c05-c30-local-20261013/final-audit.py)
