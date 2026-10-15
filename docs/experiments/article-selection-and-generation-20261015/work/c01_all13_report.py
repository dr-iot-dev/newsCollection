import json
import re
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'outputs/C01-all13-selection-20261015'
inputs=json.loads((OUT/'input-all13.json').read_text(encoding='utf-8'))
execution=json.loads((OUT/'selection-execution.json').read_text(encoding='utf-8'))
result=(OUT/'selection-result.md').read_text(encoding='utf-8')
assert len(inputs)==13 and len({a['article_id'] for a in inputs})==13
assert sum(a['body_chars'] for a in inputs)==29624
assert execution['model']=='gpt-4.1-2025-04-14'
assert re.search(r'selection_status[：:]\s*TWO_SETS',result)
assert '記事ID：F312, F965, F955' in result
assert '記事ID：F312, F965, F823' in result
assert 'G2：△' in result and 'G3：△' in result
summary={'cluster_id':'C01','requested_label':'C0, interpreted as preceding C01','input_articles':13,'input_body_chars':29624,'combinations_requested':286,'model':execution['model'],'temperature':0,'model_selection_status':'TWO_SETS','model_reported_eligible_set_count':2,'model_primary_ids':['F312','F965','F955'],'model_reserve_ids':['F312','F965','F823'],'assistant_review':{'primary':'Does not satisfy strict category criterion: home routers and business access point are mixed','reserve':'Fails mandatory conditions in the model output itself: G2 and G3 marked partial; also individual products versus a portfolio','passed_sets_confirmed':0,'note':'This does not establish that no valid set exists among all 13 articles.'},'generation_performed':False,'external_evaluation_model_used':False,'successful_api_calls':1,'usage':execution['usage']}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
labels={'F312':('Aterm 19000T12BE','家庭用Wi-Fi 7ルーター'),'F584':('HYBRID Wi-Fi 5G NC03','5G対応モバイルルーター。クレードルによる据え置き利用も記載'),'F965':('WXR9300BE6P','家庭用Wi-Fi 7ルーター'),'F042':('iGS03MP／iGS03MP-G／iGS03M','LTE・Wi-Fi・BLEゲートウェイ'),'F955':('WBE700','中小規模ビジネス向けWi-Fi 7アクセスポイント'),'F690':('ACERA 332C／332P','IoT向けWi-Fi HaLowアクセスポイント'),'F289':('iG350B','産業向けLTE Cat.1 bisマイクロゲートウェイ'),'F794':('MLR-400','LoRaマルチバンド無線モジュール'),'F006':('ST956','産業用IoT／M2Mルーター'),'F823':('Extreme Wi-Fi 7アクセスポイント群','企業・教育・医療・大規模施設向けAP群'),'F281':('PLANET-BB ミニマムプラン','IoT向け衛星通信プラン'),'F392':('アクロスWiFi','海外レンタルWi-Fiサービス'),'F689':('CMP180等','Wi-Fi 8チップセットのテスト・検証装置')}
table=['| 重心順位 | 記事ID | 主な対象 | 用途・カテゴリ |','| --- | --- | --- | --- |']
for a in inputs:
    name,cat=labels[a['article_id']]
    table.append(f'| {a["centroid_rank"]} | {a["article_id"]} | [{name}]({a["url"]}) | {cat} |')
report='''# C01全13記事を入力したGPT-4.1の記事選定結果

実施日：2026年10月15日（日本時間）。ユーザーの「C0」は直前のC01を指すものとして実施した。

## 結果

GPT-4.1はTWO_SETSを返し、第一候補をF312・F965・F955、予備候補をF312・F965・F823とした。ただし、前回と同じ厳格な採否条件に照らすと、そのまま適切な2組を得られたとはいえない。

第一候補には家庭用ルーターと業務用アクセスポイントが混在する。予備候補はさらに個別製品と製品群を混在させ、モデル自身がG2（カテゴリ・粒度一致）とG3（読者・目的一致）を「△」と記載している。「必須条件をすべて満たす組だけを採用」という指示に対して、出力自体が矛盾している。

この報告ではモデルの原文を保存し、モデルが2組を提示した事実と、このチャットによる条件適合性の確認を区別する。比較記事生成は今回の依頼範囲に含めず、実施していない。

## 実行条件

| 項目 | 設定・結果 |
| --- | --- |
| 入力 | C01所属の全13記事、本文29,624文字 |
| 入力順 | 前回と同じ重心順。今回は上位7件で切らず13件すべて |
| 選択モデル | gpt-4.1-2025-04-14 |
| temperature | 0（前回と同じ） |
| 検討するよう指示した組数 | 13件から3件の286通り |
| 指示の変更 | 「7記事」を「13記事」、「全35通り」を「全286通り」に置換 |
| 維持した条件 | G1〜G6、共通軸3つ以上、意味のある違い2つ以上、最大2組、不足時は1組・0組可 |
| 前回モデル出力・不適理由の入力 | なし |
| API実行 | 1回成功、再選定・再プロンプトなし |
| トークン | 入力24,769、出力3,014、合計27,783 |

全記事は保存済み本文から取得し、タイトルと本文のハッシュを確認した。外部検索で資料を補わず、記事本文を切り詰めていない。

## モデルが選んだ第一候補

| 記事ID | 対象 | 重心順位 |
| --- | --- | --- |
| F312 | NEC Aterm 19000T12BE | 1 |
| F965 | バッファロー WXR9300BE6P | 3 |
| F955 | NETGEAR WBE700 | 5 |

比較テーマは「家庭・小規模オフィス向けWi-Fi 7対応無線LAN機器（ルータ/アクセスポイント）の比較」。モデルはG1〜G6をすべて合格とした。

しかし、WBE700は原資料で「中小規模ビジネス向けのデュアルバンドWiFi 7アクセスポイント」と明記される。[F955:P003] 家庭用ルーター2機種と同じ具体的カテゴリとして採用するには、前回の「カテゴリ横断を対象外とする」という条件を広げる必要がある。今回の条件では採用できる組として確認していない。

また、モデルはG4で速度・管理機能・価格等について全製品の情報があると説明する一方、自身の表でWXR9300BE6Pの最大無線速度・管理機能・価格を不明としている。情報のない項目を必須共通比較軸の根拠として数えてはならない。

この第一候補の3記事はすべて前回の上位7件にも含まれる。候補範囲を13件に広げて新たに加わった記事を、第一候補に使ったわけではない。

## モデルが選んだ予備候補

| 記事ID | 対象 | 重心順位 |
| --- | --- | --- |
| F312 | NEC Aterm 19000T12BE | 1 |
| F965 | バッファロー WXR9300BE6P | 3 |
| F823 | Extreme Networks Wi-Fi 7 AP群 | 10 |

比較テーマは「家庭〜大規模施設向けのWi-Fi 7対応無線LAN機器」。F955を、今回追加した範囲のF823へ差し替えている。

モデルはG2を「△：家庭用ルータと法人・大規模向けAP群」、G3を「△：読者の利用規模が広がり、目的が拡散」と記載しながら、予備候補として採用した。この時点で必須条件をすべて満たすという契約に反する。比較単位も、個別製品と複数シリーズの製品群でそろっていない。

原資料との照合でも、次の問題がある。

- F823のAP3020等を「デュアルバンド」とする根拠が本文にない。本文の「2x2無線設計」は周波数帯の数を表す記述ではない。[F823:P007]
- F823のセキュリティ欄に追加した「WPA3」は、今回の原資料に記載されていない。[F823全文]
- 有線ポートの比較で、Aterm・WXRの10GbpsとExtremeの「PoE+（802.3at）」を並べている。後者の本文記載は給電を伴う運用条件であり、同じ通信速度の値ではない。[F823:P006]
- 前回と同様に、WXR9300BE6Pの発売時期を記事の日付から推測している。原資料でその発売日は確認できない。[F965全文]

## 7記事入力から変わった点

| 項目 | 前回：重心上位7記事 | 今回：全13記事 |
| --- | --- | --- |
| モデルの出力 | ONE_SET | TWO_SETS |
| 第一候補 | F312・F584・F965 | F312・F965・F955 |
| 予備候補 | なし | F312・F965・F823 |
| 主なカテゴリ混在 | 家庭用とモバイルのルーター | 家庭用ルーターと業務用AP |
| 今回の厳格な条件に適合する組を確認できた数 | 前回の生成段階で0組 | 今回の選定出力の確認では0組 |

前回はF955を「アクセスポイントなのでカテゴリが異なる」として除外したが、今回は同じ採否条件で第一候補に採用した。出力から確認できるのは、対象範囲の拡張による選定結果とカテゴリ境界の判断の変化である。

また、F042・F289・F006は、選ばれた家庭向けWi-Fi機器のカテゴリと異なるという理由で一括して不採用となった。この3記事を別の産業IoT向けの組として見た場合のG1〜G6の判定は出力されていない。その組が適切だと確認したわけではないが、クラスター全体から別テーマの組も検討するという今回の目的では、確認すべき候補群が出力上十分に扱われていない。

286通りの検討を指示したものの、各組の判定表は返されていない。モデル内部での網羅的な検討の有無は確認できない。また、この結果は、13記事の中に適切な組が存在しないことを証明するものではない。

今回の結論は「全13記事を渡すだけでは、適切な2組の選定には至らなかった」である。改善を試すなら、まず全13記事を具体的な用途・役割で分け、各グループ内の組ごとに必須条件を判定してから候補を順位付けする、という指示の修正が考えられる。今回はその追加実験は実施していない。

## 全13記事

'''+ '\n'.join(table)+'''

## 保存した記録

- [GPT-4.1の選定結果原文](selection-result.md)
- [実際に使用した選択指示](selection-prompt.txt)
- [入力13記事の本文・段落番号](input-all13.json)
- [実行結果JSON](summary.json)
- [API実行のモデル名・トークン数](selection-execution.json)

条件適合性の確認はこのチャットのアシスタントによるもので、別の評価モデルによる採点ではない。
'''
(OUT/'report.md').write_text(report,encoding='utf-8')
print(json.dumps({'report':str(OUT/'report.md'),'selector_status':'TWO_SETS','primary':summary['model_primary_ids'],'reserve':summary['model_reserve_ids'],'generation_performed':False,'checks_passed':True},ensure_ascii=False))
