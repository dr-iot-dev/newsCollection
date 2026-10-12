# NewsWeave 記事生成モジュールの独立化設計・実施計画

作成・更新日: 2026-10-12（日本時間）  
状態: 独立 CLI・wheel と生成側 export adapter を実装済み。稼働環境への適用は未実施。
実装済みの起動手順・初版の範囲は [実装手順](independent-apps-implementation.md) を参照。
関連: [WPuploader との機能分離計画](../../WPuploader/docs/newsweave-separation-plan-20261012.md)

## 1. 設計の目的と独立の意味

記事生成を、必要な入力成果物だけあれば単独実行できる七つのモジュールに分ける。相手のモジュール、NewsWeave の DB/API/スケジューラー、WordPress がなくても、各モジュールの処理を完了できるようにする。

独立とは「前工程が不要」ではなく、「前工程の実行環境を必要としない」こと。執筆には根拠のある記事パッケージ、検証には原稿とその根拠が必要であり、それらを外部からファイルで与えれば動作する。必要入力がない場合は明示的に不足を返し、DB から暗黙に補わない。

最初から各モジュールを常時稼働する HTTP サービスにしない。独立した Python wheel/CLI とファイル入出力を基本とし、同じ実行管理からプロセスとして呼ぶ。将来の遠隔実行でも同じ契約を使えるが、ネットワークサービス化は初版の必須条件としない。

不足資料の追加収集は fetch_missing_sources=false を既定とし、明示的な有効化時だけ行う。無効でも手元の資料による生成と通常の収集は独立して利用できる。

生成側 PostgreSQL は統合運転の実行管理・履歴・重複予約に残す。単独 CLI は PostgreSQL を要求せず、入力・出力ディレクトリと必要な外部サービスの設定だけで動作する。各モジュール専用 DB や broker を七つ用意する構成は採用しない。

## 2. 現行構造とそのままでは独立しない理由

- app/modules/ 配下には収集、抽出、選定、比較、執筆、検証等の処理が既にある。既存ロジックと契約を利用し、編集方針を保つ。
- app/modules/acquisition/service.py、web.py は Session、Source、RawSnapshot、Item、ModuleMessage 等へ直接アクセスする。入力の source ID だけでは単独収集できない。
- app/orchestration/editorial.py が facts、選定、比較、原稿作成、検証、review、状態遷移を束ね、必要情報を DB から補っている。
- VerificationPort は原稿だけを受け取る形だが、実際の verify は ArticlePackage、元記事本文、執筆モデル記録を DB から読む。単独検証にはそれらを明示入力にする必要がある。
- ComparisonPort の候補 decision には ID 参照があり、比較資料そのものがなければ独立処理できない。
- app/ai/runner.py の AIRunner は Session と AiRun 保存を要求する。AI 呼び出しと監査記録生成を DB 保存から切り離す必要がある。
- app/infrastructure/db/repositories/messages.py は同一 DB 内の enqueue と payload hash 重複排除を提供するが、他プロセスへ渡す自己完結データの役割は果たしていない。
- tests/architecture/test_module_boundaries.py は他モジュール内部の import を制限し、執筆・検証の直接 I/O を制限している。しかし独立 build/install/run、隠れた DB 参照、AI adapter 経由の依存までは保証しない。

単なるフォルダー移動ではなく、処理に必要な情報を成果物へまとめ、DB 保存・実行順の制御を外へ出す。

## 3. 七つの独立モジュール

| モジュール / 提案 CLI | 入力 | 出力 | 外部依存 |
| --- | --- | --- | --- |
| collect / nw-collect | FetchPlanV1: 承認済みソース設定、URL/検索条件、取得方針、必要なら cursor snapshot | SourceBatchV1: 元データ bytes、取得 URL/日時/hash、利用条件・robots 記録、次 cursor | 許可した収集先の HTTP。必要な収集 credential のみ |
| ground / nw-ground | SourceBatchV1、必要なら重複判定の baseline snapshot | EvidenceBatchV1: 正規化本文、照合済み facts、根拠位置、権利・品質・重複判定、実抽出モデル記録 | facts 抽出 AI。本文抽出と根拠照合は決定的処理 |
| curate / nw-curate | 主資料 EvidenceBatch、候補 corpus snapshot、比較方針、任意の前回 checkpoint | ArticlePackageV1 を含む自己完結 package、または不足理由・checkpoint（収集有効時だけ FetchPlan） | 選定・比較 AI/embedding を使用する場合のみ。その adapter はこのモジュール内 |
| write / nw-write | 自己完結 ArticlePackage、執筆方針、明示 article/draft/revision 情報 | ArticleDraftV1: 本文・比較表・出典・段落 facts 対応、執筆実モデル記録 | 執筆 AI。元サイトへアクセスしない |
| verify / nw-verify | 原稿、対応 ArticlePackage、必要な元資料本文・根拠、実執筆モデル、検証方針 | VerificationReportV1: pass/fail/error、対象 hash、criteria、実検証モデル記録 | 検証 AI。元サイトへアクセスしない |
| illustrate / nw-illustrate | 原稿、カテゴリ、画像方針 | ImageAssetV1: 検査済み JPEG、alt/caption、prompt/実モデル/hash/寸法、または明示 skip | 画像生成 AI。投稿先・Publication を要求しない |
| assemble / nw-assemble | 原稿、ArticlePackage、検証、画像または skip、必要なら ApprovalRecord | 完成 .nwdraft、ローカル preview、組み立て結果 | 外部ネットワーク不要。WordPress ID/設定を要求しない |

人間 review は八つ目の必須常駐モジュールにしない。ローカル preview と ApprovalRecordV1 を読み書きする任意ツール/API とし、assembler の入力にする。REVIEW_REQUIRED=true の運用では必須入力、false では省略できる。

### 境界をこの粒度にする理由

本文抽出・facts 抽出・根拠照合は同じ元資料を必要とするため ground にまとめる。候補選定・比較調査・比較分析・記事パッケージ化は候補の根拠を共有するため curate にまとめる。内部関数は引き続き分けても、プロセス境界の DTO や往復を増やさない。

write と verify は入力データを共有しても実行と実モデルを独立させる。画像は失敗・再生成・コストが本文とは異なるため分離する。assemble は検査と決定的な整形だけを行い、欠けた原稿や facts を AI で補わない。

## 4. 共通インタフェースを一つにする

各モジュールの公開操作は次の一つを基本とする。

~~~text
nw-<module> run --request request.json --output output-dir --config module-config.toml
~~~

ライブラリでも run(request, execution_context) -> result を公開する。execution_context は、そのモジュールだけの設定・外部サービス adapter・ローカル artifact 読み書きであり、Session や他モジュールの service object を渡さない。アルゴリズム内部は pure function として試験できるよう維持する。

### 4.1 Request

共通 Request の中心は schema_version、module、inputs、parameters の四項目とする。inputs は role → file/hash の辞書。module 固有の巨大な RPC request を毎回設計しない。

以下は説明用例であり、そのまま実行する fixture ではない。

~~~json
{
  "schema_version": "1.0",
  "module": "write",
  "inputs": {
    "package": {
      "file": "inputs/article-package.nwstage",
      "sha256": "<実際のファイルhash>"
    }
  },
  "parameters": {
    "article_id": "<UUID>",
    "revision": 1,
    "language": "ja"
  }
}
~~~

パスは request の所在を基準にした相対パスとし、許可した入力ルート内に収まることを検査する。URL や DB ID を自動解決する汎用 resolver は設けない。CLI が与える外側の入力ルートは任意のローカル配置でよい。

module-config はそのモジュールで必要な設定だけを持つ。API キーは環境変数等から読み、request・bundle・result へ出力しない。model/prompt/policy 等の実効設定 fingerprint は結果と job key に記録し、設定変更が古い処理と同一扱いにならないようにする。

### 4.2 Result

共通 Result は schema_version、job_key、outcome、outputs、issues、provenance を基本とする。

- outcome は success / needs_input / rejected / error の四種類。
- outputs は role → 完成 file/hash。途中 file を成功として列挙しない。
- issues は code、detail、retryable、必要な入力 role 等。stack trace や秘密情報を含めない。
- provenance は実 module version、policy/prompt/model、入力 hash、UTC 実行日時、attempt ID、使用量等。
- verification の判定 fail は「検証処理が正常に完了した結果」であり、Result は success、VerificationReport の overall_result は fail とする。needs_input と処理失敗を混同しない。
- AI の応答消失など結果不明は error + AI_RESULT_UNCERTAIN、初版では retryable=false。盲目的な有料再実行を避ける。

process 終了コードは 0=success、10=needs_input、20=rejected、30=error を提案する。終了コードと result を照合し、不一致・result 不在は実行失敗とする。ログは stderr、正式な出力は file。終了コードだけで業務判定をしない。

### 4.3 自己完結の StageBundle

途中成果物は .nwstage（通常 ZIP）に統一する。種類の違いは manifest の contract_type と payload の Schema で表す。

~~~text
manifest.json                   # transport version、contract type/version、file 一覧/hash、provenance
payload.json                    # その工程の公開 DTO
assets/...                      # 元 HTML/本文/画像など、その消費者に必要な bytes
~~~

manifest と公開・hash 検査は全モジュールで同じ。payload は既存の NormalizedContent/Evidence/ArticlePackage/Draft/Verification を基に、隠れた参照を除いた新版とする。種類を七つの独自 transport にしない。

ID は監査用のラベルとして保持できるが、ID が示す DB 行を必要にしない。facts は本文・根拠文字位置・出典と照合できる情報を同梱する。writer に不要な元 HTML は執筆 input に送らず、verify には原文照合に必要な本文を同梱する。すべての工程へ原文全集・全監査記録をコピーしない。

初版は module 間で必要な資料を bundle に含め、中央 artifact service を必須にしない。大規模 corpus は統合 runner が候補を絞った immutable batch を渡す。内容選別と切り捨て理由を記録し、module が外部 DB の最新状態を勝手に取りに行かない。

StageBundle の payload には現行 DTO の confidence/quality 等の小数があり、その型を勝手に整数へ変えない。外側 manifest は file bytes の SHA-256 を検査するので、検査のため payload を再シリアライズする必要はない。manifest の canonicalization は DraftBundle と同じ規則に揃え、小数を含む payload は固定 serializer と適合 fixture で扱う。JSON NaN/Infinity・重複キーは禁止する。

.zip の安全検査、.part→完成公開、完成後変更禁止は WP 分離計画と共通仕様にする。ただし .nwstage と WPuploader 向け .nwdraft の contract は区別し、uploader に途中 bundle の読解を要求しない。

## 5. 簡潔なデータの流れ

~~~mermaid
flowchart LR
    F[FetchPlan] --> C[collect]
    C --> S[SourceBatch]
    S --> G[ground]
    G --> E[EvidenceBatch / 候補 corpus]
    E --> K[curate]
    K --> P[ArticlePackage]
    K -. 追加収集が有効な場合のみ .-> F
    P --> A[write]
    A --> D[ArticleDraft]
    D --> V[verify]
    P --> V
    D --> I[illustrate]
    D --> B[assemble]
    P --> B
    V --> B
    I --> B
    H[任意 ApprovalRecord] --> B
    B --> O[完成 .nwdraft]
~~~

verify の SourceBatch/元本文は、対応 ArticlePackage の verification 用資産に含めるか evidence role で明示入力する。DB から補わない。初版の自動運転は verify pass 後に illustrate を開始して課金を抑える。単独 illustrate は原稿だけで実行可能で、検証環境の存在を要求しない。

### 不足資料の追加収集オプション（既定: 無効）

不足資料の追加収集を有効・無効にする共通方針として fetch_missing_sources を設ける。統合 runner と単独 collect の環境変数は FETCH_MISSING_SOURCES、config の項目は fetch_missing_sources、既定値はいずれも false とする。明示的に有効化しない限り不足資料を収集しない。

この設定の対象は、資料数や比較項目の不足を補うための外部検索、新規記事取得、既存ソースの再取得・更新である。通常の登録ソースの定期収集、利用者が明示的に指定した通常収集、手元の corpus からの選定・比較とは分ける。資料の不足を「通常収集」として迂回させない。

| 状況 | fetch_missing_sources=false（既定） | fetch_missing_sources=true |
| --- | --- | --- |
| 手元の根拠だけで要件を満たす | その資料で選定・比較・執筆へ進む | 同じ。不要な追加収集をしない |
| 資料数・比較根拠が不足 | needs_input、MISSING_SOURCE_FETCH_DISABLED、不足項目・checkpoint を返す。取得ジョブと取得用 FetchPlan を自動作成しない | needs_input と不足項目・FetchPlan・checkpoint を返し、runner が上限内で収集する |
| 手動で資料を追加した | 新 corpus/input hash で処理を再開できる | 同じ |
| 同じ不足状態のまま周期実行 | 結果を再利用し、追加取得も無意味な AI 再実行もしない | 有限の探索回数・予算・新規入力の条件で再試行 |
| 保存済みの不足資料取得ジョブ | paused_policy として保持。新しい remote 取得を開始しない | 対象 revision/hash と許可・予算を再確認したうえで再開可能 |

不足であっても検証・出典数・根拠照合の条件は緩めず、推測で記事を完成させない。資料が揃わない原稿は needs_input で正常停止し、他の原稿は継続する。needs_input は例外や全体障害として扱わない。

### 設定と簡潔な Request の関係

共通 Request を増やさず、既存 parameters の中に任意の fetch_missing_sources を置く。未指定なら実行側の実効設定を継承し、初期状態は false。

統合 runner の信頼済み設定（または明示 CLI --fetch-missing-sources / --no-fetch-missing-sources）を上限とする。Request の true で実行側の false を解除しない。実効値は「実行側の設定 AND Request の指定値（未指定なら継承）」とし、false を指定した job は実行側が有効でも収集しない。CLI の明示指定は実行側の設定を変更する操作であり、入力ファイルによる許可の書き換えとは区別する。

採用する実行側の優先順は明示 CLI > 環境変数 > config > 既定 false。実効値を curator の parameters、job_key の設定 fingerprint、checkpoint と Result provenance に記録し、後から有効・無効を切り替えても古い入力や許可を混ぜない。

FetchPlanV1 には purpose を必須項目として追加し、scheduled / explicit / missing_sources の三種類を使う。curate が作る計画は必ず missing_sources。runner の dispatch と collect の開始時・各 remote 取得の直前の両方で、missing_sources と実効 flag を確認する。古い request で purpose が欠けている場合は adapter が既知の起点から補い、判定できなければ無効側へ保留する。

設定変更の反映は runner/worker の明示 reload または停止・再起動で行い、設定ファイルを書き換えただけで常駐プロセスへ反映されるとはしない。反映完了後は、既に通信を開始した一件は完了・保存し得るが、次の検索・取得・再取得は開始しない。queue に残る仕事や常駐中の worker も巡回・取得開始前に設定を確認する。有効化し直しても既に進行した原稿や古い計画を無条件に再開しない。

### 有効時だけ行う不足資料の往復

curate は collect/ground を同期呼び出ししない。収集有効時だけ needs_input と FetchPlan、進捗 checkpoint、既に確認した候補・除外理由を出す。無効時も不足理由・checkpoint は返すが、外部取得を指示しない。

有効時、runner は許可ソース・上限・回数を確認して collect→ground を実行し、新しい corpus と checkpoint で curate を再実行する。単独 curate の利用者は、設定が無効でも別の手段で同じ資料を用意して再実行できる。runner がなければ needs_input で正常停止し、存在しない module を待って hang しない。

最大調査回数、記事数、AI 呼び出し予算は入力方針へ固定する。同じ input hash の反復で資料が増えていなければ探索を打ち切る。無効・有効どちらでも needs_input を無限 retry にしない。

### 現行設定からの移行

現行 app/core/config.py、.env.example、compose.yaml には COMPARISON_AUTO_RESEARCH と RESEARCH_REFRESH_SOURCES があり、refresh は既定 true になっている。実装時は不足資料収集の統一 flag を追加し、Settings の既定値、.env.example、compose の fallback をすべて false に揃える。

COMPARISON_AUTO_RESEARCH は手元資料の自動調査・比較と区別して扱い、不足資料収集を止めるためにローカル比較まで止めない。過渡期に RESEARCH_REFRESH_SOURCES を参照する旧 adapter は、新 flag の実効値を refresh 許可の上限として使う。既存 .env の旧 refresh=true だけで不足資料収集が有効にならないようにする。最終の独立 module では fetch_missing_sources を公開方針とし、相反する二つの公開スイッチを残さない。

入口は orchestration/research.py の refresh、追加調査 queue、discovery/pair の追加取得、関連 acquisition adapter、CLI と jobs/scheduler.py。不足補完の経路を列挙して同じ判定を入れ、収集を一つの経路だけで止める実装にしない。

## 6. 生成品質と組み立て時の検査

検証は原稿だけでなく、同じ ArticlePackage hash、原稿 hash、必要な出典本文、実執筆モデル記録を対象にする。実検証モデルとの独立性、段落 facts、比較表、数値・固有名詞、出典数、コピー判定、権利・品質条件を維持する。設定値だけから使用モデルを推測しない。

assembler は次を検査する。

1. 原稿、package、verification が同じ article/revision と入力 hash を参照している。
2. verification の pass が対象原稿に対するもので、policy・モデル独立条件を満たす。
3. 画像の入力 draft hash と asset hash が一致する。画像なしは明示 skip。
4. review 必須なら ApprovalRecord の actor、decision、対象 draft/package/image hash、チェックリスト、必要な複数人確認が揃う。
5. 出典数、分類キー、shadow 禁止、文字数、HTML allowlist 等の export 条件を満たす。

verify が検査する意味内容と、assembler が追加する「使用モデル」等の表示・metadata を区別する。VerificationReport に draft_hash/package_hash、assembler に render_binding（入力 draft hash、renderer version、完成 HTML hash）を記録する。最終 HTML を verifier が直接見たかのような履歴を作らない。

完成 .nwdraft の日時・ID は入力 snapshot から固定し、assembler の今回の実行日時・attempt ID は Result の監査記録だけへ置く。同じ入力 snapshot の再組み立てで ZIP bytes を変えない。

assembler は本文の主張・比較 facts を変更しない。内容変更が必要なら新 revision で write/verify をやり直す。画像だけの変更も新 artifact_revision と必要な review を伴わせる。生成側はこの完成 bundle をそのまま WPuploader へ渡す。

## 7. 薄い runner と保存の責務

runner は生成の制御役であり、各 module の利用に必須なサービスではない。統合運転では既存 PostgreSQL を利用し、次だけを管理する。

- 入出力 snapshot・hash の登録、実行計画、依存工程の完了条件。
- module のプロセス起動、結果受理、再試行上限・次回日時・予算。fetch_missing_sources の確認と無効時の不足補完 dispatch 抑止。
- 生成全体の出典集合予約、article/revision の採番、最新原稿の選択。
- AI 実行記録等を result から DB へ保存する adapter。
- 完成 bundle の export 待ち、任意 receipt の表示用取り込み。

比較や文章生成のルールを runner へ戻さない。module が返した不足や fail を pass に書き換えない。DB transaction を AI/HTTP/子プロセス完了まで保持しない。

job_key は module/version、入力 role ごとの content hash、意味を持つ parameters、policy/prompt/model の実効 fingerprint から作る。file の保存先、run 日時、API キーは key に含めない。結果受理は job_key と attempt ID を照合し、旧入力の遅い結果で最新 revision を巻き戻さない。

### 重複防止の扱い

自動記事生成の source-set claim は runner が短い DB transaction と UNIQUE 制約で取得する。候補の近似重複判定は ground/curate が入力 baseline に対して行い、グローバル予約とは分ける。候補 corpus の同時更新は新 snapshot として扱い、実行中の入力を変更しない。

単独 CLI は存在しない全環境の生成履歴までは判断できない。入力 article/revision と job_key に対する同一結果の再利用を行い、別記事を自動採番しない。統合運転の重複予約と WPuploader の target/source_set 予約で、自動生成・投稿時の既存規則を保持する。

## 8. 同時実行・失敗・再実行

統合 runner の同じ job_key の予約は DB の一意性で管理する。module 自身も共通ローカル作業領域の job_key ごとの OS lock を実際の実行プロセスが保持する。parent runner が落ちても生きている module のロックを時間だけで奪わない。別ホストの同じ仕事への自動 takeover は初版では対応せず、ホスト障害時は旧プロセス停止確認後に再開する。

module は output/.part/<attempt_id> に書き、全 hash を検査後に完成領域へ公開する。result は成果物完成後に確定する。出力・SQLite 補助 cache・OS lock の状態保存先はローカル、NAS には完成成果物だけを配信する。worker ごとの一時領域は他の worker が削除しない。

| 停止箇所・問題 | 再開方針 |
| --- | --- |
| module 呼び出し前に runner 停止 | 未実行 job を再予約する |
| module が完成 file を公開後、runner DB 保存前に停止 | result・input hash を再検査して受理。AI を再実行しない |
| 部分 file だけ残る | 完成扱いにせず、保存済み入力で再実行。試行・課金上限を守る |
| 同一 job を並行開始 | 予約・OS lock で一つだけ実行。既存完成結果を他方へ返す |
| 入力の package ID と hash が食い違う | conflict。別 article の本文や承認を混ぜない |
| AI 応答不正・不足情報 | error または needs_input。合格にせず、他記事は続ける |
| AI 実行後、結果保存前に応答消失 | AI_RESULT_UNCERTAIN として対象試行を保留。遠隔課金の exactly-once は保証しない |
| 設定/policy/model が変更された | 新 job_key。旧結果を現在の実行として再利用しない |
| 入力 snapshot が古くなった | その入力の結果として保存。新 snapshot/revision を上書きしない |
| assemble だけ失敗 | 既存 draft/verification/image から再組み立て。再生成・再課金しない |
| 生成 DB が停止 | 単独 CLI は動作。統合 runner の登録/予約だけを待機 |

有料 API の自動 retry は module 設定の回数・予算を満たす明確な retryable error に限定する。不明な完了は自動再課金しない。モジュールごとの failure を隔離し、別原稿は処理できるようにする。

## 9. 物理配置と独立 build

~~~text
newsWeave/
  components/
    collect/       pyproject.toml + src/nw_collect/ + tests/
    ground/        pyproject.toml + src/nw_ground/ + tests/
    curate/        pyproject.toml + src/nw_curate/ + tests/
    write/         pyproject.toml + src/nw_write/ + tests/
    verify/        pyproject.toml + src/nw_verify/ + tests/
    illustrate/    pyproject.toml + src/nw_illustrate/ + tests/
    assemble/      pyproject.toml + src/nw_assemble/ + tests/
  protocols/       versioned Schema、packaging 規則、golden fixtures
  app/             移行中の API/runner/DB adapter
~~~

一つのリポジトリで管理しても、それぞれの wheel と必要な小さい設定だけでインストール・実行できる。親 app、他 component、PostgreSQL、WordPress の import は不可。

protocol の小さい reader/writer・検査 helper は版を固定し、必要部分を build 時に各 wheel に同梱する。他 component の editable install や実行時に親 protocols フォルダーを見る方式にしない。配布物に同梱した Schema/fixtures で互換性を保証する。共有 helper に AI provider、DB、編集ポリシー、他 module 呼び出しを持たせない。

AI adapter、画像 adapter、執筆/検証 policy 等はそれを使う component に同梱し、外部依存は各 pyproject へ宣言する。複数 module が必要とする小さい決定的 policy は版付きで同梱・適合試験を行う。大きな共通 app を全 module に要求する実装へ戻さない。

## 10. 既存コードからの抽出計画

| 対象 | 移行内容 |
| --- | --- |
| acquisition/service.py、web.py、connectors.py、http.py、robots.py、sources/config.py | Source 等の DB model を SourceSpec/FetchPlan と cursor snapshot に置換。取得 bytes と実行結果を返す collect core と DB 保存 adapter を分ける |
| extraction/service.py、facts.py、deduplication/service.py、core/content.py | ground へ抽出。DB が読む source snapshot や重複 baseline を明示入力にする |
| selection/service.py、comparison/service.py、analysis.py、research/service.py、topics.py | curate 内の private 処理へ。候補の facts/本文/除外履歴を input にする |
| orchestration/research.py、comparison_analysis.py、comparison_selection.py、comparison_discovery.py、comparison_pair_discovery.py、関連 core | 算法・AI prompt を curate、取得・再調査の実行制御を runner/collect へ。研究依頼は needs_input、不足理由、収集有効時だけ FetchPlan へ変換 |
| writing/service.py、core/draft_style.py、article_tables.py、evidence_support.py | write に必要な policy を同梱。DB で補う facts・モデル・category を入力へ |
| verification/service.py、EditorialService.verify | pure 検査と AI 検証を verify へ。原文・package・writer model を明示入力に追加 |
| ai/runner.py | provider call、出力検証、実モデル/usage 記録生成を component adapter へ。AiRun 保存は result 受理側の DB adapter へ |
| ai/images.py、image_styles.py、orchestration/featured_images.py | 生成と検査を illustrate へ。Publication/WordPress 依存は削除し uploader と分離 |
| publication/service.py の rendering、model_disclosure.py | assemble の決定的 rendering/記録整形へ。WP payload 解決は WPuploader |
| orchestration/editorial.py、phase2.py、editorial_jobs.py、jobs/scheduler.py | module を呼ぶ薄い runner と DB adapter に置換。巨大 EditorialService の業務処理を残さない |
| contracts/*_v1.py、envelope.py、model-contracts.json | 公開 contract と内部 AI DTO を分類し、公開 contract から隠れた DB 参照を除去した新版を作る |
| tests/architecture/test_module_boundaries.py | core の I/O 制限を維持し、component の別 build/install と隠れた DB・相互 import の禁止へ広げる |

## 11. 実施順序と WPuploader 計画との接続

### G1: transport・公開契約・適合例

共通 Request/Result/StageBundle、必要な role、hash・serializer、固定 UUID 規則、policy fingerprint、最大サイズを固定する。fetch_missing_sources の既定 false、Request の制限、FetchPlan の purpose、無効/有効両モードを契約へ追加する。現行の正常・失敗・不足・shadow 例を外部 DB 不要な fixture に変換する。

成果物: protocols、各 component skeleton、既存 DTO→新契約 adapter。
完了条件: 別環境に持ち込んだ file だけで contract を検査でき、全 component が同じ transport を使用する。

### G2: write と verify を先に独立させる

純粋処理が比較的まとまっている執筆・検証を先に抽出する。AI runner の DB 保存を分離し、検証に必要な原文・package・writer model を明示入力へ追加する。

成果物: nw-write/nw-verify wheel/CLI、旧 DB adapter、出力比較試験。
完了条件: app/、DB、他 component がない環境で正常/失敗の原稿を処理でき、現行の品質条件を満たす。

### G3: illustrate と assemble を独立させる

画像を draft 入力だけで生成可能にし、既存 bytes/実モデルを再利用する。assembler に適格性・review・render_binding と .nwdraft 出力を実装する。

成果物: nw-illustrate/nw-assemble、生成側ローカル preview、WP 受け渡し fixture。
完了条件: WordPress と Publication がなくても完成 .nwdraft を作成できる。

この段階は WP 分離計画 Phase 2 の生成側実装に対応する。G1〜G3 と WP 分離 Phase 1〜3 が揃えば、上流の collect/ground/curate を旧 adapter 経由のまま、投稿機能を先に独立化できる。

### G4: collect と ground を独立させる

収集と保存を分離し、approved source/cursor の snapshot 化、raw bytes、本文・facts・根拠の自己完結化を実施する。collect に purpose/flag の判定を入れ、runner の dispatch と併せて不足補完を既定で停止する。Settings・.env.example・compose の既定値を false に統一し、保存済み取得 queue の停止・再開も実装する。重複 baseline の snapshot とグローバル claim の責務を分ける。

完了条件: collect は他 module/DB なしで取得成果物を返し、ground はネットワーク収集を呼ばずに supplied bytes から照合済み根拠を作成する。

### G5: curate と追加調査ループを独立させる

既存比較・discovery・pair-selection 等を私有実装として整理し、candidate corpus と needs_input/checkpoint に統一する。runner に明示有効時だけの取得・ground 再実行と予算制御を移す。無効時は手元の corpus だけで判断し、不足のまま新しい input がなければ周期 retry しない。既存探索モードの適格性と shadow 制約を維持する。

完了条件: corpus のみで比較パッケージを作れ、既定では不足理由・checkpoint だけを返す。有効時だけ FetchPlan を返し、他 component を同期呼び出しせず有限回で探索を停止する。

### G6: 統合 runner 切り替えと依存削除

旧 DB 入出力 adapter と新 file 契約を併存させて fixture と隔離運転で比較し、工程ごとに新 runner へ切り替える。同一原稿・工程の旧/new 実行を同時に有効にせず、既存 AI 結果の再利用で重複課金を避ける。

完了条件: 生成全工程が新 contract で接続され、各 component の単独配布・実行が確認できる。API/DB/スケジューラーの障害が単独 CLI の起動を妨げない。旧巨大 orchestration と隠れた DB 照会を除去する。

### 切り替え・ロールバック

各工程の切り替え前に旧入力・出力・実モデル・根拠対応を snapshot として保存する。新工程停止時は既存完成成果物を保持し、旧 adapter が読める版へ変換してその工程だけ戻す。旧工程へ戻すために本文や画像を再生成しない。

WPuploader の投稿履歴は生成工程の切り替えとは別管理とし、生成の rollback で post/media を再作成しない。

## 12. 受入条件

| 試験 | 条件 |
| --- | --- |
| 各 wheel を空環境へ単独 install | 他 component、親 app、NewsWeave DB を置かず CLI が起動・実行 |
| input file を別 directory/ホストへコピー | 明示 role/hash だけで処理。元 DB ID の解決要求なし |
| verify に draft だけを与える | package/原文/モデル不足を明示。暗黙 DB lookup や推測なし |
| writer と verifier のモデルが同一/履歴欠落 | 独立モデル条件を pass にしない |
| 設定未指定・curate の資料不足 | needs_input、不足理由・checkpoint。補完用外部検索/取得/更新・取得 queue 作成はゼロ |
| 既定無効でも手元の資料が十分 | ローカル資料から ArticlePackage を作成して後続へ進む |
| 明示有効・不足資料の取得 | 許可ソース・回数・予算内でだけ FetchPlan→collect→ground を実行 |
| 実行側 false / Request true | 入力 file で許可を解除できず、補完取得ゼロ |
| 実行側 true / Request false | 対象 job だけ補完取得ゼロ |
| 無効化時に補完 queue・worker が存在 | 新しい remote 取得を開始せず個別保留。開始済み結果を保存 |
| 同じ不足入力の反復・設定切り替え | 無効時は無意味な取得/AI 再実行ゼロ。有効化後は版・hash・予算を再確認 |
| 通常定期収集・明示通常収集 | 不足補完の無効化では停止しない。purpose の偽装による迂回は拒否 |
| 既存の旧 refresh=true と新 flag 未設定 | 不足資料収集は false のまま |
| curate の不足判定 | needs_input と checkpoint。有効時だけ FetchPlan。同期 collect 呼び出しなし |
| corpus snapshot の並行更新 | 実行中 input は変わらず、新版を別 job として扱う |
| 同一 job_key の並行処理・完了後強制終了 | 結果一件に収束し、完成成果物を再利用 |
| AI 応答消失・不正出力 | 不明試行を無制限再課金せず fail/error として隔離 |
| 古い attempt の結果が遅延到着 | 最新 draft/report を巻き戻さない |
| assemble の再実行 | 同じ snapshot から同じ .nwdraft bytes、AI/WordPress 呼び出しゼロ |
| review/画像と draft hash の不一致 | 完成 bundle を作らず対象のみ保留 |
| malformed ZIP/Schema/hash | 未受理、他記事は処理継続 |
| 単独実行と統合 runner | 同じ入力/policy の決定的出力と判定が一致 |
| 既存編集要件の regression | 比較表、根拠、出典数、実モデル表示、文体・数値等を維持 |
| component 間の transport 検査 | Request/Result/StageBundle の共通契約に適合し、相互 import ゼロ |

AI 本文の byte 完全一致をモデルの非決定性に対する合格条件にしない。fixture/mock による決定的判定、保存済み実出力の再利用、品質制約の regression と実環境 smoke test を区別する。

## 13. 対応範囲

七つの工程は単独実行・配布可能にする。一方、統合運転の全環境重複管理、探索順序、予算、最新版採番は runner の責務として残す。単独利用でも必須入力を揃えれば runner を要求しない。

公開契約は一つの実行操作、Request/Result、自己完結 StageBundle に揃え、内部 AI DTO や監査テーブルをそのままプロセス境界に公開しない。公開 contract は「消費者が単独で必要情報を検査できる範囲」に絞る。

今後の WP 投稿タイプは現行 news_weave/news-weave と通常 post/posts を対象にし、旧投稿タイプの互換・route 移行を新 component や新 uploader に持ち込まない。

