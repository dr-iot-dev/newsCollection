import json
import re
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'outputs/C02-all11-selection-20261015'
articles=json.loads((OUT/'input-all11.json').read_text(encoding='utf-8'))
execution=json.loads((OUT/'selection-execution.json').read_text(encoding='utf-8'))
selection=(OUT/'selection-result.md').read_text(encoding='utf-8')
assert len(articles)==11 and len({a['article_id'] for a in articles})==11
assert sum(a['body_chars'] for a in articles)==25386
assert execution['model']=='gpt-4.1-2025-04-14'
assert re.search(r'selection_status[：:]\s*TWO_SETS',selection)
assert '記事ID：F234（SKC）、F039（CLOUDSHIP®・RealBoard®）、F118（Smart Craft）' in selection
assert '記事ID：F118（Smart Craft）、F342（SmartMat Cloud）、F301（Q-Smart）' in selection
summary={'cluster_id':'C02','input_articles':11,'body_chars':25386,'combinations_requested':165,'model':execution['model'],'temperature':0,'model_selection_status':'TWO_SETS','model_reported_eligible_set_count':2,'model_primary_ids':['F234','F039','F118'],'model_reserve_ids':['F118','F342','F301'],'assistant_review':{'primary':'Needs reconsideration: different monitoring objects and collection mechanisms, data platform versus integrated MES versus purpose-built monitoring, unsupported integration and quotation assumptions','reserve':'Inappropriate under strict category and purpose criteria: inventory management and quality management were combined under broad manufacturing data digitization','sets_confirmed_appropriate_as_returned':0,'all_possible_sets_independently_rejected':False},'generation_performed':False,'external_evaluation_model_used':False,'successful_api_calls':1,'usage':execution['usage']}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
labels={'F234':('Smart Kaizen Counter（SKC）','プレス加工機の稼働監視・生産実績自動収集'),'F301':('Q-Smart','検査記録・品質データ管理、品質改善支援'),'F039':('CLOUDSHIP・RealBoard','時系列データ基盤と分析システムによる工場稼働監視の導入事例'),'F118':('Smart Craft','工程・品質・在庫を統合するMES。今回の発表は工程と在庫の連動'),'F342':('SmartMat Cloud','IoTによる実在庫の把握・発注支援の導入事例'),'F121':('sinops-CLOUD AI値引','小売・惣菜の値引き判断とシール発行'),'F007':('esm IoT','設備監視とアフターサービス・保守業務の連携'),'F638':('PRIMO-X','板金業向け図面管理'),'F142':('Patt Plus','製造・建設現場の安全管理・動線管理'),'F556':('Sveaverken F200','農機の自動操舵'),'F808':('Silex Microsystems関連','企業買収の発表')}
table=['| 重心順位 | 記事ID | 主な対象 | 用途・記事の内容 |','| --- | --- | --- | --- |']
for a in articles:
    name,cat=labels[a['article_id']]
    table.append(f'| {a["centroid_rank"]} | {a["article_id"]} | [{name}]({a["url"]}) | {cat} |')
report='''# C02全11記事を入力したGPT-4.1の記事選定結果

実施日：2026年10月15日（日本時間）。

## 結果

GPT-4.1はTWO_SETSを返した。第一候補はF234・F039・F118、予備候補はF118・F342・F301である。モデルは両組についてG1〜G6をすべて合格とし、適切な組の数を2と報告した。

ただし、本文と前回の厳格な採否基準を照合すると、第一候補は比較する役割・対象と根拠の再検討が必要であり、予備候補は在庫管理と品質管理を広い上位概念でまとめている。返されたまま適切と確認できた組は0である。

これは今回のモデル出力が十分でないという結果であり、C02の全165組の中に適切な組が存在しないと結論したものではない。今回は記事選択の実験であり、比較記事の生成は行っていない。

## 実行条件

| 項目 | 設定・結果 |
| --- | --- |
| 入力 | C02に属する全11記事、本文25,386文字 |
| 入力順 | 元の埋め込みから重心順を再計算し、11記事すべてを入力 |
| 指示した組数 | 11記事から3記事を選ぶ165通り |
| 選択モデル | gpt-4.1-2025-04-14 |
| temperature | 0 |
| 指示変更 | 最初の指示の「7記事」を「11記事」、「全35通り」を「全165通り」に変更 |
| 維持した採否条件 | G1〜G6、共通軸3つ以上、意味のある違い2つ以上、適切な組が不足する場合は1組・0組を許容 |
| 過去の比較記事・モデル応答の入力 | なし |
| API呼び出し | 1回成功。再プロンプト・再選定なし |
| トークン | 入力22,293、出力3,238、合計25,531 |
| 別モデルでの評価・採点 | 実施せず |

11記事の保存済み本文とタイトルのハッシュを確認した。原資料の本文を省略せず段落番号付きで渡した。採否条件の追加・変更、外部検索による根拠の補完は行っていない。

## 第一候補：F234・F039・F118

| 記事ID | 対象 | 重心順位 | 本文に記載された中心的な役割 |
| --- | --- | --- | --- |
| F234 | Smart Kaizen Counter（SKC） | 1 | プレス機にセンサーを設置し、稼働状態・生産実績を自動収集 |
| F039 | CLOUDSHIP・RealBoard | 3 | PLC等から設備データを集め、データ基盤と専用ダッシュボードで稼働監視 |
| F118 | Smart Craft | 4 | 工程の実績入力と在庫数を連動させる、工程・品質・在庫管理のMES |

モデルの比較テーマは「製造業向け現場データのリアルタイム可視化・稼働監視・実績収集サービスの比較」。工場の現場責任者・経営者が、生産状況の把握・分析のために選ぶという設定だった。

この組は予備候補よりも生産実績の収集・可視化という接点が明確である。一方、そのまま採用するには次の問題がある。

1. 比較する対象データが異なる。SKCはプレス機の稼働中・停止中・段取り中と生産実績を自動収集する。[F234:P009〜P011] CLOUDSHIP・RealBoardはPLCや旧設備から収集した稼働データを扱う。[F039:P003,P013,P018] Smart Craftの記事の「リアルタイム」は、作業者の工程実績入力に応じて在庫数が更新される仕組みである。[F118:P009〜P014] この3つを、同じ機械稼働監視機能のリアルタイム性能として扱うことはできない。
2. 専用の監視・実績収集サービス、データ基盤と分析システムによる個別構築事例、統合MESが混在する。「同じ具体的カテゴリ・比較単位」というG2の合格根拠は十分ではない。特に、自社でどこまで構築するか、工程・品質・在庫まで管理する必要があるかで選択課題が変わる。
3. 「SKCのAIスケジューラー連携」は本文に記載がない。F234:P004は共同開発元の一社が最適ワークスのユーザーだったという背景であり、SKCの製品連携機能の説明ではない。
4. CLOUDSHIP・RealBoardの価格欄にある「個別見積もり想定」は原資料で確認できない。価格不明は価格不明として扱う必要がある。
5. モデルは価格等の全対象情報があると説明しつつ、自身の根拠表では2対象を未記載としている。価格を全対象の情報がそろう必須共通軸として数えることはできない。ただし、価格の未記載だけで不適と判定しているわけではない。

したがって、このチャットによる確認では「第一候補は要再検討」とした。自動計測か手入力かという違い自体を禁止するのではなく、何を把握したい読者にとっての代替案なのかを具体的に固定し、同じ比較軸で成立することを示す必要がある。

## 予備候補：F118・F342・F301

| 記事ID | 対象 | 重心順位 | 本文に記載された中心的な役割 |
| --- | --- | --- | --- |
| F118 | Smart Craft | 4 | 工程実績と在庫管理の連動、MES |
| F342 | SmartMat Cloud | 5 | 実在庫をIoTで把握し、在庫適正化・発注を支援 |
| F301 | Q-Smart | 2 | 検査結果・不良情報・工程変更履歴を管理し、品質改善を支援 |

モデルの比較テーマは「製造業向け現場データの統合管理・在庫・品質管理SaaSの比較」。第一候補からF234とF039を外し、F342とF301を加えた。F118だけが共通する。

この組は、今回の厳格なカテゴリ・目的の一致条件では不適である。

- SmartMat Cloudは実在庫の把握・発注判断・在庫最適化を支援する。[F342:P007〜P013,P016]
- Q-Smartは検査記録、4M変化と不良の関係、品質データ分析を支援する。[F301:P002〜P003,P009〜P014]
- モデル自身も、Q-Smartに在庫管理機能の記載がなく、SmartMat Cloudに品質管理機能の記載がないと認めている。
- それでも「現場データのデジタル化・効率化」という広い目的で合格にしており、今回禁止したカテゴリの拡張に当たる。

さらに、Q-Smartの「即時集計・可視化」という説明には注意が必要である。本文は入力後のサマリー自動算出を説明しているが、更新遅延などリアルタイム性の性能条件を示していない。AI自動分析は今後の実装予定であり、実装済み機能との区別も必要である。[F301:P010,P022]

## 今回の選定で残る点

モデルはF007のesm IoTを、アフターサービス・保守管理が主目的であるとして除外した。原資料にもその用途は明記されているため、単に「稼働監視」という共通語だけで他候補と同一視することはできない。一方、全165通りについての個別判定表は返されておらず、F007を含む別の組などを網羅的に評価したかは出力から確認できない。

今回の結果は、全記事を渡すだけではカテゴリ・目的の異なるサービスをまとめる傾向と、根拠表の不正確さが残ったことを示す。クラスター自体に適切な組が存在しないという証明ではない。

## 入力した全11記事

'''+ '\n'.join(table)+'''

## 記録

- [GPT-4.1の選定結果原文](selection-result.md)
- [使用した選択指示](selection-prompt.txt)
- [入力全11記事の本文・段落番号](input-all11.json)
- [実行結果JSON](summary.json)
- [モデル名・トークン数・実行時間](selection-execution.json)

適合性の確認はこのチャットのアシスタントが行った。別モデルによる評価や比較記事の生成は実施していない。
'''
(OUT/'report.md').write_text(report,encoding='utf-8')
print(json.dumps({'validated':True,'report':str(OUT/'report.md'),'selector_status':'TWO_SETS','primary':summary['model_primary_ids'],'reserve':summary['model_reserve_ids'],'generation_performed':False},ensure_ascii=False))
