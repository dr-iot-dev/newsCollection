# 比較項目の動的抽出：実装記録

実施日：2026-10-12（日本時間）。[設計・実装計画](comparison-dynamic-axis-design-plan-20261012.md)に基づくshadow経路を追加した。[IoT評価結果](comparison-dynamic-axis-iot-evaluation-20261012.md)を参照。

## 実装した工程

1. 取得・本文抽出済みの3〜5資料を入力し、Discoveryで候補を生成する。候補の件数上限はなく、同分野で一般的に比較される共通項目を短い軸名にする。機械的に分割しない。出力は項目ID・名称・質問・4層・関連記載箇所のみ。
2. 候補軸を固定して、各記事の値・条件・情報状態を個別に抽出する。
3. コードで製品重複と根拠を検証し、厳密な過半数（3製品：2、4製品：3、5製品：3）を計算する。
4. 全候補を意味評価し、過半数・質問適合・有用性・非重複を満たす軸から最大6項目を選ぶ。4〜6項目は目安、成立判定の既定最低数は従来に合わせ3項目。
5. 元資料を渡して、別モデルで独立検証する。
6. 同じ選定目的で、値・根拠・条件に不備がある場合は、同じ資料・候補軸・製品同一性を保って1巡だけ値を修正し、被覆率を再計算して再選定・独立再検証する。不合格は理由付きで保留する。

Discoveryで値の対応状態、比較可否、優劣を判定しない。4層からの最低採用数も要求しない。修正工程でも候補質問の追加・変更や別モデルへの迂回は行わない。

## 根拠・履歴・出力

- LLMは記事IDと段落IDを選び、コードが原文引用と文字位置へ復元する。表示名や質問に、検索語の原文一致制約を持ち込まない。
- Structured Outputsの実行時スキーマで記事ID・段落ID・項目ID・回答／評価件数を拘束する。値の数値は引用で確認し、意味と条件は独立検証する。
- 候補・抽出・選定・初回検証・修正・最終検証を `module_messages` と `ai_runs` に保存する。新規DB移行は不要。
- API呼出予算は工程ごとの応答修復も含む。各応答の修復は最大1回、独立検証後の値修正は別に最大1巡。途中再開は入力・設定・モデル・プロンプトが一致する場合のみ許可する。
- PostgreSQLでは同一run_idの同時実行を防ぐ。再開時は検証済みAI履歴と一致するキャッシュだけを使う。
- 常時 `audit.json`、`ai-runs.json`、`candidates.json`、`axis-search.json`、`coverage.csv`、`metrics.json` を出力する。AI検証通過時だけ `selection.json` と `comparison.md` を出力する。
- `selection.json` は `selection_only=true` と凍結hashを持つ比較用資料であり、記事・公開の承認ではない。別run_idの出力先への上書きは拒否する。

## 実行方法

比較計画・抽出・検証のモデル設定を用いる。独立検証モデルは他の工程のモデルと異なる必要がある。実評価ではplanner=gpt-5.2、extractor/repair=gpt-4.1、reviewer=gpt-5.1、入力上限200,000文字・出力上限16,000 tokensとした。本番設定は変更していない。

```powershell
news-weave comparison-axes discover --item ARTICLE_UUID_1 --item ARTICLE_UUID_2 --item ARTICLE_UUID_3 --output .local/axes-run --call-budget 20
news-weave comparison-axes resume RUN_UUID --output .local/axes-run --call-budget 20
news-weave comparison-axes export RUN_UUID --output .local/axes-run
```

`--item` は3〜5件、`--editorial-intent` は任意。CLIは再開用run_idを返す。終了コードはAI検証通過0、保留・予算停止・再試行待ち2、コマンドエラー1。

## 主な変更箇所・検証

- `app/contracts/comparison_dynamic_axes_v1.py`：候補・段落参照・値・選定・検証・実行状態。
- `app/ai/dynamic_axes_prompts.py`、`app/ai/runner.py`：工程別プロンプト、実行時の出力拘束、モデル履歴。
- `app/core/comparison_dynamic_axes.py`：根拠復元・製品重複・過半数・項目集合の検証。
- `app/orchestration/comparison_dynamic_axes.py`、`app/dynamic_axes_cli.py`：実行・1巡修正・再開・出力。
- `tests/unit/test_comparison_dynamic_axes.py`：3〜5件の過半数境界、根拠の反復・不正参照、固定軸、製品重複、再開・設定変更・キャッシュ改変、不合格保留、修正途中再開、出力混在防止、CLI識別子。
- `tools/export_model_contracts.py`、`docs/model-contracts.json`：公開プロンプト・スキーマを更新。

ruff・mypy（121ソース）通過。SQLite/PostgreSQLを含む全体回帰試験は866件通過・1件skip。

## 現在の範囲

資料群の形成は入力側の工程とし、現行のペア探索は維持する。新CLIは比較用資料までを生成し、自動記事生成・WordPress送信には接続していない。実評価は本番DBを読み取り専用で参照し、コピーした資料と別SQLite DBを使用した。IoT評価で残った誤抽出が解消されるまで、記事生成への採用は保留する。


## Discoveryの候補数制限の修正

2026-10-12の追加指示により、プロンプトの6〜8件という目安と、候補契約2種類の最大8件制約を撤去した。一部の記事だけに現れる差分も列挙し、記録／可視化／エクスポート、料金／契約／試用／導入支援のような複合項目を分割する。後段の選定件数とは分離する。以前のIoT評価の8候補は修正前の記録。追加評価はDiscoveryだけを対象とする。

Discoveryのみの追加実行は5記事で74候補、3記事で58候補を出力した。[候補全件・実行条件・残る粒度の課題](comparison-dynamic-axis-discovery-expanded-20261012.md)を参照。関連テスト26件通過・18件skip、ruff・mypy通過。

## 語句検索に使える共通軸への修正

記事固有の細目・セット別価格の軸を一般的な共通名へまとめる。軸名は括弧なしの短い名詞句とし、各軸に原文にあるsearch_termsを追加した。AIを使わないOR文字列検索で一致語を返すmatching_axis_termsを追加し、全候補の検索語と記事別一致をaxis-search.jsonへ常時出力する。過去の引用付き候補は空の検索語でも読めるが、新規Discoveryでは検索語を必須として検証する。現在のプロンプトは以前の機械的分割指示を置き換える。[現行の候補・検索結果](comparison-dynamic-axis-discovery-searchable-20261012.md)を参照。

--discovery-onlyを追加し、候補抽出後にcandidates_readyで終了する。値抽出・選定・独立検証は呼ばない。新規候補は語句検索で2記事以上に出現することを確認し、広すぎる説明語や原文にない検索語を除く。最終のIoT例は5記事で10候補、3記事で7候補。現在の関連テスト41件通過・33件skip、ruff・mypy通過。[現行の抽出結果と検索方法](comparison-dynamic-axis-discovery-searchable-20261012.md)を参照。
