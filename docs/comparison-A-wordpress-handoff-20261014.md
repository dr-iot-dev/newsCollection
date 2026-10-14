# A一括判定からWordPress下書きへの受け渡し

**指示修正後の位置づけ：本報告とv7の実行契約は履歴です。現在の検証は比較記事1本ずつ行います。指示は[A案の理解と修正した検証指示](comparison-A-instructions-20261014.md)を参照してください。v7には出力契約の不整合と住宅IoTの表の出典割当誤りがあり、3件という結果を修正後のAの確定結果として扱いません。修正指示の個別評価は[全30クラスターの個別評価結果](comparison-A-individual-all30-results-20261014.md)を参照してください。実WordPress投稿は未実施です。**

更新日：2026-10-14。ユーザー決定によりAを採用。既存原資料・生成時マーク・本文を再利用し、**Aの合格結果3件をWPuploaderが読む.nwdraftへ出力した。WordPressへの投稿は未実施。**

## 採用した処理

原資料の照合・比較成立・品質採点・全21ペアの重複確認をAの一括1回で行う。後段に追加の意味判定は置かない。生成時の適否マークと不適理由は入力に残し、肯定的な確認理由や以前のpass判定を正解として渡さない。完全な生成記録は保存したままである。

GPT-4.1での指示修正では見逃しが残ったため、最終Aの判定モデルはgpt-5.2-2025-12-11、reasoning=mediumとした。生成の実行記録はgpt-4.1-mini-2025-04-14を保持し、文章編集と表・出典整形を別の来歴として表示する。A/B比較時の旧モデル・数値は過去の実測として変更しない。

## 指示・出力契約の修正

- 原資料忠実性を先行のpassに固定しない。表の各値・本文段落の根拠確認を先に出し、その後で適否を決める。
- 原資料にない機能・限定的な対応・将来予定・市場一般論を補わない。引用IDが実在するだけで支持されたと扱わない。
- 記事の目的・比較対象の列挙・根拠に沿った編集説明と、製品の事実主張を区別する。「資料で確認できず」は非対応を意味しない。
- 同じ読者の具体的な判断に役割差が役立つ比較は認める。勝者、同じ物件種別、予算の数値、専用チェックリストを新たな必須条件にしない。
- 3条件が全てpassのときだけ品質採点する。不適・未確認は通常点null。WordPress向け12項目にも合格が必要である。
- 引用の所属、必須項目の欠落、判定と根拠・点数の不整合、同一本文・同一出典集合を機械検査する。これらは新しい意味判定ではない。

健康管理・住宅IoT・医療AIでは、保存本文を再利用して具体的な読者目的を明記し、根拠のない市場一般論と重複リードを整理した。医療AIの安全性は実行統制の設計として範囲を絞った。修正した本文そのものをAへ渡し、合格後に未評価の本文修正はしていない。出典URLのリンク化とモデル表示は決定的レンダーとして行う。

## Aの最終結果

|記事|A判定|通常点|受け渡し|
|---|---|---:|---|
|H008-1 業界別データ活用プラットフォームの用途と導入形態|ineligible|—|対象外|
|H012-0 健康管理サービスの支援方法と計測・データ共有の違い|eligible|84|下書きファイル作成済み|
|H015-0 企業ITのネットワーク・ブラウザ・データ基盤の役割|ineligible|—|対象外|
|H020-0 共同農園・わさび栽培設備・家庭向けアプリの用途|ineligible|—|対象外|
|H023-0 住宅IoTの導入方式と居住者向け機能・運用の違い|ineligible|—|対象外|
|H029-0 企画支援・メディア計画・ナレッジ管理のAIサービス|eligible|79|下書きファイル作成済み|
|H030-0 医療AIの院内業務・予約対応・安全実行基盤の役割|eligible|86|下書きファイル作成済み|

C08/C15/C20/C23を今回の受け渡しから除外した。これはAの不適判定又はA出力の必須整合検査によるもので、追加の原資料点検で覆した結果ではない。C08/C15のsupportedに根拠IDがない箇所、C23の明細と原資料忠実性のstatusの不一致は技術記録に残している。元のモデル応答は変更していない。

## 下書きファイルと確認用プレビュー

|テーマ|Aの点|.nwdraft|確認用Markdown|HTMLプレビュー|
|---|---:|---|---|---|
|健康管理サービスの支援方法と計測・データ共有の違い|84|[原稿ファイル](../.local/comparison-A-wordpress-20261014-v7/ready/H012-0-07179aa5-981d-5adf-8938-2d3375930ab3.nwdraft)|[本文](../.local/comparison-A-wordpress-20261014-v7/preview/H012-0.md)|[プレビュー](../.local/comparison-A-wordpress-20261014-v7/preview/H012-0.html)|
|企画支援・メディア計画・ナレッジ管理のAIサービス|79|[原稿ファイル](../.local/comparison-A-wordpress-20261014-v7/ready/H029-0-9ff4894d-d621-583f-b3d4-acecab8d6c89.nwdraft)|[本文](../.local/comparison-A-wordpress-20261014-v7/preview/H029-0.md)|[プレビュー](../.local/comparison-A-wordpress-20261014-v7/preview/H029-0.html)|
|医療AIの院内業務・予約対応・安全実行基盤の役割|86|[原稿ファイル](../.local/comparison-A-wordpress-20261014-v7/ready/H030-0-50aa2a1a-3fa9-556d-bb63-a889bc2482db.nwdraft)|[本文](../.local/comparison-A-wordpress-20261014-v7/preview/H030-0.md)|[プレビュー](../.local/comparison-A-wordpress-20261014-v7/preview/H030-0.html)|

## WPuploaderで受け取る方法

NewsWeaveはWordPressの送信資格情報を持つ処理を追加せず、既存の独立WPuploaderへ完成ファイルを渡す。稼働先と既存履歴を保持したWPuploaderで、各ファイルをimportする。

~~~console
wpuploader --state-dir <既存のローカル台帳> import <原稿.nwdraft>
wpuploader --state-dir <既存のローカル台帳> dry-run
~~~

共有受け渡しを使う場合は、ready/の3ファイルをWPUPLOADER_TRANSFER_DIR/ready/へ配置する。接続・分類設定を確認した既存アップローダーのrun-once/watchが下書きとして送る。現在の投稿履歴があるサイト用に空の台帳を作り直さない。投稿statusはdraft固定である。今回は画像を生成しておらず、featured_image=null、image_skip_reason=disabledを記録した。

## 再実行と検証

このCLIは今回の保存済み7候補を対象とする。再実行は次の順で行う。成功済みA応答と完成ファイルは再利用し、応答が不明なAPI要求を無条件に再送しない。

~~~console
python tools/prepare_marked_wordpress_drafts.py prepare
python tools/prepare_marked_wordpress_drafts.py evaluate
python tools/prepare_marked_wordpress_drafts.py export
python tools/check_marked_wordpress_handoff.py
~~~

14件のユニットテストとruffが通過した。実装済みWPuploaderのread_bundle/validate_draft/import_file/prepareを隔離した一時SQLite台帳で実行し、3件の取込、再import時の非重複、出典リンク、draft固定、送信準備を確認した。実CMSへの通信は0件。原生成時ineligible6件と元の共通検証での追加除外1件も保持している。

最終Aは7記事を1要求で判定し、保存usageに基づく概算はUSD 0.956168。今回の指示・スキーマ調整試行（欠落・出力途中終了を含む）を全て含めた概算はUSD 4.545471。本文生成API・画像API・B方式の実行は追加していない。成功以外の応答使用量も費用台帳に含めた。請求実績ではない。単価は[OpenAIのGPT-5.2仕様](https://developers.openai.com/api/docs/models/gpt-5.2)と保存時のGPT-4.1単価で計算した。

## 証跡

- [Aの実応答・判定](../.local/comparison-A-wordpress-20261014-v7/assessment.json)
- [受け渡し一覧](../.local/comparison-A-wordpress-20261014-v7/handoff.json)
- [既存WPuploaderの取込検査](../.local/comparison-A-wordpress-20261014-v7/uploader-dry-run.json)
- [入力・出力の結び付きと検査](../.local/comparison-A-wordpress-20261014-v7/validation.json)
- [費用台帳](../.local/comparison-A-wordpress-20261014-v7/cost-ledger.json)
- [今回の選定記録](../.local/comparison-A-wordpress-20261014-v7/selection.json)
- [実装](../nw_generation/marked_comparison.py)・[実行CLI](../tools/prepare_marked_wordpress_drafts.py)
- [履歴のA/B比較](comparison-generation-marked-reevaluation-20261014.md)
