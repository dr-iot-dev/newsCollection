import hashlib
import json
import re
from collections import Counter
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
WORK=BASE/'work/c03-c10-allarticles-trial'
OUT=BASE/'outputs/C03-C10-allarticles-selection-20261015'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

reviews={
 'C03':{
  'primary':['F010','F456','F932'],'reserve':['F865','F456','F932'],
  'primary_theme':'HARMONY／Navie／GeN：顧客対応AI',
  'reserve_theme':'AvaTwin Chatbot／Navie／GeN：問い合わせ対応AI',
  'primary_review':'要再検討。有人コンタクトセンター運営支援と、利用者が直接使う自動回答エージェントの役割が異なる。',
  'reserve_review':'候補として有望。ただし比較軸の修正が必要。誤回答率・自己解決率・コスト削減を同じ指標として扱わない。',
  'overview':'第一候補は役割の混在。予備候補は比較候補として有望だが根拠表を修正する必要がある。',
  'evidence':[
   {'finding':'HARMONYの本文はAmazon Connectベースの有人コンタクトセンター運営、SV支援、文字起こし、通話分析、RPA連携を説明する。Navie・GeNの自己解決型エージェントと同一の直接代替品とする根拠は十分でない。','refs':['F010:P002','F010:P003','F010:P034','F456:P007','F932:P001','F932:P002']},
   {'finding':'HARMONYの資料からの語彙抽出は、文字起こし・要約の精度向上のための機能である。Navie・GeNの回答用ナレッジ化と同じ目的の学習として扱わない。','refs':['F010:P021','F010:P022','F010:P023','F010:P024','F456:P013','F456:P014','F932:P013','F932:P014']},
   {'finding':'予備候補はWeb上の問い合わせ自動回答という用途を設定できる。回答に使う資料・質問理解の方法・導入方法など、同じ意味で根拠を整理し直す余地がある。これは本チャットの観察であり、GPT-4.1を再実行して得た候補ではない。','refs':['F865:P005','F865:P010','F865:P013','F865:P023','F456:P010','F456:P014','F456:P018','F932:P014','F932:P016']},
   {'finding':'AvaTwinの0.1%未満は同社条件の事実に基づかない回答の発生率。GeNの約80%は有人チャットへ移行せず終了した割合。Navieのコスト削減は同社試算であり、実測の自己解決率とは異なる。モデルの自己解決率行は同じ指標の比較になっていない。','refs':['F865:P014','F865:P016','F456:P020','F932:P002','F932:P003']}
  ]},
 'C04':{
  'primary':['F017','F140','F303'],'reserve':['F017','F140','F135'],
  'primary_theme':'ServiceNow／Zscaler／Vectra AI：AI活用型セキュリティ基盤',
  'reserve_theme':'ServiceNow／Zscaler／Cohesity：防御・復旧基盤',
  'primary_review':'要再検討。製品群全体と個別のSOC・検知機能で比較範囲が異なり、提供予定機能の混在もある。',
  'reserve_review':'今回の厳格なカテゴリ・目的基準では不適。防御・SOC運用とAI基盤のバックアップ・復旧という補完的な役割を混在させている。',
  'overview':'第一候補は比較範囲・提供時期の整理が必要。予備候補は防御と復旧の混在。',
  'evidence':[
   {'finding':'ServiceNow Autonomous Securityは6つの統合ソリューションを包含する。Zscaler Agentic SOC、Vectraの検知・調査支援と比較する場合、何を選ぶ読者なのか、ServiceNowのどの機能・単位を対象にするのかを固定する必要がある。','refs':['F017:P005','F017:P010','F017:P023','F017:P024','F140:P002','F140:P024','F140:P026','F303:P007','F303:P011','F303:P013']},
   {'finding':'ServiceNowのTier 2 SOC AIスペシャリストなどは2026年12月提供予定と本文に明記される。モデルはこれらを現行の自動化機能として並べ、G6も合格にしている。提供中と予定を分けて記載する必要がある。','refs':['F017:P024','F017:P032','F140:P032']},
   {'finding':'Cohesity Agent Resilienceの主目的はAIエージェントを支えるインフラと関連資源の保護・復旧であり、検知・ガバナンスだけでは解消できない復旧のギャップを埋めるものと説明される。SOC防御基盤に代わる同一目的の候補として扱うと役割がずれる。','refs':['F135:P004','F135:P013','F135:P022','F135:P023','F135:P024']},
   {'finding':'Cohesityは一部顧客向け提供で一般提供は2026年末予定。自動化構想と個別の提供済み機能も分ける必要がある。','refs':['F135:P005','F135:P009','F135:P011','F135:P030','F135:P032']}
  ]},
 'C05':{'primary':None,'reserve':None,'primary_theme':'なし','reserve_theme':'なし','primary_review':'モデルが選定不可と判定。','reserve_review':'なし。','overview':'モデルは選定不可。水位・漏水・浄化槽・農業・介護などで監視対象と利用者が異なる。','evidence':[]},
 'C06':{'primary':None,'reserve':None,'primary_theme':'なし','reserve_theme':'なし','primary_review':'モデルが選定不可と判定。','reserve_review':'なし。','overview':'モデルは選定不可。外観検査関連も食品用装置・塗装用測定器・学習基盤で用途と比較単位が異なる。','evidence':[]},
 'C07':{'primary':None,'reserve':None,'primary_theme':'なし','reserve_theme':'なし','primary_review':'モデルが選定不可と判定。','reserve_review':'なし。','overview':'モデルは選定不可。用途の分散に加え、F809とF876はほぼ同じ内容と判定。','evidence':[]},
 'C08':{
  'primary':['F038','F429','F518'],'reserve':['F038','F429','F110'],
  'primary_theme':'xPilot／Vusion／mcframe X：クラウド業務基盤',
  'reserve_theme':'xPilot／Vusion／e-Stand：現場データ活用',
  'primary_review':'不適。小売店舗運営プラットフォーム2件に製造業ERPを組み合わせ、DX・業務効率化という広い共通語で採用している。',
  'reserve_review':'不適。小売向け2件に建設業ダッシュボードを組み合わせている。モデル自身もG2を△としており、必須条件の全合格という指示に反する。',
  'overview':'両組とも不適。小売・製造・建設の異なる業務をDXという上位概念でまとめている。',
  'evidence':[
   {'finding':'xPilotは小売店舗のリアルタイム実行、Vusionは小売店の電子棚札と店舗運営、mcframe Xは製造業ERP、e-Standは建設現場ダッシュボードである。同じ読者が同じ業務課題のために選ぶ代替候補ではない。','refs':['F038:P001','F038:P002','F429:P001','F429:P003','F518:P001','F518:P003','F110:P001','F110:P002','F110:P003']},
   {'finding':'予備候補のG2を△としながらTWO_SETSとして採用している。これは元記事の解釈以前に、必須条件をすべて満たす組だけを返すという指示との矛盾である。','refs':[]}
  ]},
 'C09':{'primary':None,'reserve':None,'primary_theme':'なし','reserve_theme':'なし','primary_review':'モデルが選定不可と判定。','reserve_review':'なし。','overview':'モデルは選定不可。メーター・ランプの点検、現場防犯、土質判別という用途が異なる。','evidence':[]},
 'C10':{
  'primary':['F950','F677','F698'],'reserve':['F950','F677','F698'],
  'primary_theme':'Xiaomi／Roborock／ECOVACS：家庭用ロボット掃除機',
  'reserve_theme':'同じ3記事のまま、ECOVACSの対象機種だけ変更',
  'primary_review':'比較候補として有望。各記事の複数機種から対象を明示し、同じ機種・仕様・価格種別にそろえる必要がある。',
  'reserve_review':'予備の記事組として無効。第一候補と同じ3記事であり、別の記事構成の予備を選ぶという指示を満たさない。',
  'overview':'第一候補が最も有望。ただし複数機種の混在を修正する必要がある。予備は同一記事組のため無効。',
  'evidence':[
   {'finding':'3記事はいずれも家庭用ロボット掃除機を実質的に説明し、水拭き方式、障害物認識、自動洗浄・乾燥、アプリ操作などの共通の比較項目が本文にある。','refs':['F950:P001','F950:P004','F950:P006','F950:P008','F677:P001','F677:P006','F677:P012','F677:P014','F677:P016','F698:P001','F698:P003','F698:P004','F698:P038','F698:P040']},
   {'finding':'第一候補ではXiaomi 6 Maxと6、ECOVACSの複数モデルを同じ列に併記している。原資料はモデル別に仕様を説明しており、その対応関係を固定しないと別モデルの値を継ぎ合わせるおそれがある。例えば6 Maxの高さは9.3cmのすき間への進入、6は高さ9cmと区別される。','refs':['F950:P004','F950:P006','F950:P012','F950:P014','F698:P001','F698:P003','F698:P005','F698:P006']},
   {'finding':'予備はF698内の比較対象をmini 2 PROに変えるだけで、F950・F677・F698という記事IDの集合は変わらない。異なる対象機種の企画案であって、別の3記事の予備ではない。','refs':['F698:P002','F698:P106','F698:P107']},
   {'finding':'吸引圧Paや洗浄温度は各社の試験条件や定義に注意する必要がある。特にECOVACSの100℃は加熱モジュールのヒーター到達最高温度と注記され、実水温とは区別される。同じ単位だけで清掃性能や実際の洗浄温度の優劣を断定しない。','refs':['F950:P128','F950:P131','F950:P133','F677:P032','F677:P033','F698:P080']}
  ]}
}

inventory={a['cluster_id']:a for a in read(OUT/'inventory.json')}
summaries=[]
raws=[]
for label,review in reviews.items():
    folder=OUT/label
    articles=read(folder/'input-articles.json')
    by_id={a['article_id']:a for a in articles}
    provenance=read(folder/'provenance.json')
    execution=read(folder/'selection-execution.json')
    response=read(WORK/label/'selection-response.json')
    request=read(WORK/label/'selection-request.json')
    intent=read(WORK/label/'selection-intent.json')
    raw=(folder/'selection-result.md').read_text(encoding='utf-8')
    assert response['status']=='completed' and response['model']==execution['model']=='gpt-4.1-2025-04-14'
    assert len(articles)==provenance['article_count']==inventory[label]['article_count']
    assert sum(a['body_chars'] for a in articles)==provenance['body_chars']
    assert hashlib.sha256(json.dumps(request,ensure_ascii=False).encode()).hexdigest()==intent['request_sha256']
    assert hashlib.sha256(request['instructions'].encode()).hexdigest()==provenance['instructions_sha256']
    assert hashlib.sha256(request['input'].encode()).hexdigest()==provenance['input_sha256']
    for a in articles:
        assert hashlib.sha256((a['title']+'\n\n'+a['body']).encode()).hexdigest()==a['input_hash']
    status=re.search(r'selection_status\s*[：:]\s*\**(TWO_SETS|ONE_SET|NO_SET)',raw).group(1)
    if review['primary'] is None:
        assert status=='NO_SET'
    else:
        assert status=='TWO_SETS'
        for key in ('primary','reserve'):
            ids=review[key]
            assert len(ids)==len(set(ids))==3 and set(ids)<=set(by_id)
            assert all(ident in raw for ident in ids)
    for evidence in review['evidence']:
        for ref in evidence['refs']:
            article_id,paragraph=ref.split(':')
            assert paragraph in {p['paragraph_id'] for p in by_id[article_id]['paragraphs']},ref
    distinct=(set(review['primary'])!=set(review['reserve'])) if review['primary'] else None
    summary={'cluster_id':label,'input_articles':len(articles),'body_chars':provenance['body_chars'],'combinations_requested':provenance['combinations_requested'],'model':execution['model'],'model_selection_status':status,'primary_ids':review['primary'],'reserve_ids':review['reserve'],'distinct_article_sets':distinct,'primary_theme':review['primary_theme'],'reserve_theme':review['reserve_theme'],'assistant_primary_review':review['primary_review'],'assistant_reserve_review':review['reserve_review'],'overview':review['overview'],'usage':execution['usage'],'generation_performed':False,'separate_evaluation_model_used':False,'no_set_is_nonexistence_proof':False}
    save(folder/'summary.json',summary)
    save(folder/'assistant-observations.json',review)
    summaries.append(summary)
    detail=[f'# {label}：全{len(articles)}記事の選定結果','',f'GPT-4.1の判定：{status}。以下の確認はこのチャットのアシスタントによるもので、別モデルの検証結果ではない。','',f'第一候補：{review["primary_theme"]}',f'記事ID：{", ".join(review["primary"] or []) or "なし"}','',f'確認結果：{review["primary_review"]}','',f'予備候補：{review["reserve_theme"]}',f'記事ID：{", ".join(review["reserve"] or []) or "なし"}','',f'確認結果：{review["reserve_review"]}','', '## 本文照合の観察','']
    if review['evidence']:
        for evidence in review['evidence']:
            detail.append('- '+evidence['finding']+(' 根拠：'+', '.join(evidence['refs'])+'。' if evidence['refs'] else ''))
    else:
        detail.extend([review['overview'],'','このクラスターではモデルが候補を返さなかった。モデルの全組み合わせに対する不存在判断を、独立した全件審査で立証したものではない。候補が返らなかった4クラスターは原資料全文と判定原文を保存し、上の理由はモデルの説明を要約した。'])
    detail.extend(['','## 入力記事','', '| 重心順位 | 記事ID | 記事名 |','| --- | --- | --- |'])
    for a in articles:detail.append(f'| {a["centroid_rank"]} | {a["article_id"]} | [{a["title"]}]({a["url"]}) |')
    detail.extend(['','## 記録','', '- [モデルの選定結果原文](selection-result.md)','- [入力記事の全文と段落番号](input-articles.json)','- [実際に使用した指示](selection-prompt.txt)','- [モデル名・トークン数](selection-execution.json)','- [機械可読結果](summary.json)','', 'この記事選択実験では比較記事を生成していない。「有望」は入力候補としての見込みであり、G1〜G6を満たす完成記事として検証済みという意味ではない。'])
    (folder/'report.md').write_text('\n'.join(detail)+'\n',encoding='utf-8')
    raws.append(f'# {label}\n\n'+raw)

totals={'clusters':len(summaries),'input_articles':sum(a['input_articles'] for a in summaries),'body_chars':sum(a['body_chars'] for a in summaries),'successful_selection_api_calls':len(summaries),'model_status_counts':dict(Counter(a['model_selection_status'] for a in summaries)),'input_tokens':sum(a['usage']['input_tokens'] for a in summaries),'output_tokens':sum(a['usage']['output_tokens'] for a in summaries),'generation_performed':False,'separate_evaluation_model_used':False}
save(OUT/'summary.json',{'totals':totals,'clusters':summaries})
(OUT/'selection-results-all.md').write_text('\n\n---\n\n'.join(raws),encoding='utf-8')

lines=['# C03〜C10：クラスター全記事を入力した記事選定実験','', '実施日：2026年10月15日（日本時間）。','', 'C03〜C10の8クラスター、全93記事を、クラスターごとにGPT-4.1へ渡して記事選択を実行した。モデルはC03・C04・C08・C10で2組ずつ、C05・C06・C07・C09では選定不可を返した。','', 'ただし、モデルが2組を返したことと、元の厳格な採否基準を満たす2組が得られたことは区別する必要がある。今回、そのまま2組を採用できると確認したクラスターはない。比較記事の入力として次に検討する候補は、C10の第一候補、およびC03の予備候補である。どちらも比較対象や比較軸の修正を要し、完成記事として検証済みという意味ではない。','', '## 一覧','', '| クラスター | 全記事数 | GPT-4.1の返答 | 第一候補の記事ID | 予備候補の記事ID | 本チャットによる確認 |','| --- | --- | --- | --- | --- | --- |']
for a in summaries:
    label=a['cluster_id']
    lines.append(f'| [{label}]({label}/report.md) | {a["input_articles"]} | {a["model_selection_status"]} | {"・".join(a["primary_ids"] or []) or "なし"} | {"・".join(a["reserve_ids"] or []) or "なし"} | {a["overview"]} |')
lines.extend(['','## 返された候補の内容',''])
for a in summaries:
    if not a['primary_ids']:continue
    lines.extend([f'### {a["cluster_id"]}','',f'- 第一候補：{a["primary_theme"]}。{a["assistant_primary_review"]}',f'- 予備候補：{a["reserve_theme"]}。{a["assistant_reserve_review"]}',''])
lines.extend(['## 特に重要な観察','', '1. C03の第一候補には、有人コンタクトセンターの運営支援システムと、利用者向けの自己解決AIが混在する。予備候補の3サービスは問い合わせ自動回答という用途が近いが、誤回答率・自己解決率・コスト削減を同じ評価指標として扱う誤りがある。','2. C04の第一候補は、包括的な6ソリューション群とSOC・検知プラットフォームで比較範囲が異なる。ServiceNowの一部機能は2026年12月提供予定であり、提供中の機能と分ける必要がある。予備のCohesityはバックアップ・復旧が主目的で、防御・SOC運用とは補完関係にある。','3. C08は小売・製造・建設の異なる業務を「DX」「業務効率化」という上位概念でまとめている。予備候補ではモデル自身が必須条件G2を△としており、全条件合格の組だけを返すという指示と矛盾する。','4. C10は家庭用ロボット掃除機というカテゴリと利用目的が最も明確にそろう。しかし、モデルは複数機種の仕様を同じ欄に併記した。比較時は各記事の対象機種を明示し、他機種の仕様を混ぜず、試験条件が異なる数値をそのまま性能順位に使わない。また予備はECOVACSの対象機種を変えただけで記事IDの組が同じであり、別の3記事の予備という条件を満たさない。','', '## 実行条件と確認範囲','', '- モデルは全件gpt-4.1-2025-04-14、temperature=0、store=false、max_output_tokens=16000。','- C01・C02と同じ選択指示を使い、記事件数と組み合わせ数だけを変更した。G1〜G6、共通比較軸3つ以上、意味のある違い2つ以上、適切な組が不足する場合に1組・0組を許す条件は変更していない。','- 全記事の「タイトル＋空行＋本文」のハッシュを保存済み埋め込みの入力ハッシュと照合した。本文を切り詰めず、段落番号を付けて入力した。','- 各クラスターの元の埋め込みを正規化し、その平均重心とのコサイン類似度順に全件を表示した。クラスターを横断して記事を混ぜていない。','- 過去に作成した比較記事、C01・C02の選定応答や指摘、その他の過去のモデル応答は選択モデルへ渡していない。','- APIはクラスターごとに1回、合計8回成功した。再選定・再プロンプトは行っていない。比較記事生成や別の評価モデルによる採点は実施していない。','- 本チャットによる確認は、候補が返った4クラスターの主要な用途・機能・数値・提供条件・構造上の不備の照合である。93記事すべての全組み合わせを独立に再評価したものではない。選定不可4クラスターの理由はモデルの説明を要約している。','- モデルには各クラスターの全組み合わせを検討するよう指示したが、全組の判定表は返されていない。NO_SETはこの試行で候補が提示されなかったという結果であり、適切な組の不存在が証明されたという意味ではない。','', '| クラスター | 記事数 | 本文文字数 | 検討を指示した組数 | 入力トークン | 出力トークン |','| --- | --- | --- | --- | --- | --- |'])
for a in summaries:lines.append(f'| {a["cluster_id"]} | {a["input_articles"]} | {a["body_chars"]:,} | {a["combinations_requested"]} | {a["usage"]["input_tokens"]:,} | {a["usage"]["output_tokens"]:,} |')
lines.extend([f'| 合計 | {totals["input_articles"]} | {totals["body_chars"]:,} | {sum(a["combinations_requested"] for a in summaries):,} | {totals["input_tokens"]:,} | {totals["output_tokens"]:,} |','', '## 原文と詳細記録','', '- [8クラスターの選定結果原文をまとめたファイル](selection-results-all.md)','- [機械可読の結果一覧](summary.json)',''])
for a in summaries:lines.append(f'- [{a["cluster_id"]}の詳細報告]({a["cluster_id"]}/report.md) ／ [選定結果原文]({a["cluster_id"]}/selection-result.md)')
(OUT/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'validated':True,'totals':totals,'report':str(OUT/'report.md'),'duplicate_reserve_detected':'C10','candidate_groups_for_further_generation':['C10 primary','C03 reserve']},ensure_ascii=False))
