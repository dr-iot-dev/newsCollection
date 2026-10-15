import hashlib
import json
import re
from collections import Counter
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
WORK=BASE/'work/c11-c30-allarticles-trial'
OUT=BASE/'outputs/C11-C30-allarticles-selection-20261015'

def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

# These are observations by this chat, kept separate from the selector's raw answer.
reviews={
'C11':{'primary':None,'reserve':None,'overview':'モデルが選定不可と判定。','reason':'事業紹介、導入事例、税務・営業・経費・コンテンツ管理などの用途が分散。','evidence':[]},
'C12':{'primary':['F443','F699','F771'],'reserve':['F443','F699','F053'],'overview':'両組とも不適。対象者・用途・提供段階の混在。','primary_review':'不適。企業向けウェルネス、自治体での高齢者フレイル実装検証、介護施設での健康変化検知実証を同じ選択肢としてまとめている。','reserve_review':'不適。企業向けウェルネス、自治体の高齢者実装検証、独居高齢者の見守り共同開発を混在。','evidence':[
 ('MIRUWS M4は健康経営企業等に提供してきたウェルネス可視化サービスの拡張であり、F699はコンソーシアムによる地域在住高齢者の実装検証、F771は介護施設での実証開始の発表である。製品・サービスの対象者、利用現場、提供段階をそろえた比較にはなっていない。',['F443:P001','F699:P001','F699:P002','F771:P001']),
 ('F053も既存の人守センサーとAIソリューションの提携・共同開発開始を説明している。AIによる次世代見守り機能がそのまま購入可能な完成サービスであると扱わない。',['F053:P003'])]},
'C13':{'primary':['F438','F065','F637'],'reserve':['F065','F637','F908'],'overview':'第一候補は有望。予備は不適。','primary_review':'候補として有望。不動産仲介の物件情報登録・入稿の手作業削減という目的がそろう。ただしFaciloの記事内の3プロダクトを混ぜず、AI駆動コンバーターを対象に固定する。','reserve_review':'不適。マイソクの店舗情報帯の編集は、物件情報登録・複数ポータル入稿とは別工程。モデル自身もG2を△としている。','evidence':[
 ('みらいえは図面情報の登録、Faciloは物件概要自動入力と複数ポータル入稿、カナリーは図面・業者間サイトからの入稿・更新支援を説明しており、同じ業務担当者の入力負担削減という接点がある。',['F438:P003','F438:P008','F065:P020','F065:P022','F065:P027','F637:P001','F637:P002']),
 ('FaciloのP033の登記情報・公図OCRは、P028から始まる簡易調査AIエージェントの説明である。AI駆動コンバーターの機能にそのまま足し合わせると比較対象の粒度が変わる。',['F065:P028','F065:P033']),
 ('F908は販売図面の店舗情報帯を差し替える機能である。入力情報を物件項目に登録する機能と同じ選択肢とする根拠は不足。',['F908:P001','F908:P002'])]},
'C14':{'primary':None,'reserve':None,'overview':'モデルが選定不可と判定。','reason':'製造業・エッジAIに接点はあるが、IoT統合、設備保全、製品実装支援などの役割・比較単位の相違を理由に候補なし。','evidence':[]},
'C15':{'primary':None,'reserve':None,'overview':'モデルが選定不可と判定。','reason':'SASE、ネットワーク運用、ブラウザ管理、資産管理、ストレージなどの具体的なカテゴリが異なると判定。','evidence':[]},
'C16':{'primary':None,'reserve':None,'overview':'応答不整合。冒頭1組・末尾0組、3記事組は未成立。','primary_review':'有効な3記事の組なし。冒頭はONE_SETだが本文ではF868・F332の2記事だけで、G1〜G6を不合格とし、末尾でNO_SETに変更している。','reserve_review':'なし。','tentative_ids':['F868','F332'],'evidence':[]},
'C17':{'primary':['F488','F333','F411'],'reserve':['F538','F541','F333'],'overview':'第一候補は条件整理が必要。予備は不適。','primary_review':'比較候補として有望だが、ツールと受託診断、Webとモバイルの対象範囲、改修支援の有無を根拠に沿って固定する必要がある。','reserve_review':'不適。AI利用リスクの専門家点検、生成AIの継続的ガバナンス管理、Web脆弱性診断を同じ目的の代替候補として扱っている。','evidence':[
 ('AeyeScanはモバイル画面の自動巡回・API連携診断等、セルバはWebサイト・Webシステムの診断と改修、SynXはWeb・モバイル等の受託診断を説明する。診断という用途には接点があるが、対象アプリ・運用主体を明確にして比較する必要がある。',['F488:P014','F488:P016','F488:P020','F333:P001','F333:P003','F333:P004','F411:P003','F411:P005']),
 ('モデルはAeyeScanを診断のみとしているが、改修支援について記載がない場合は非対応と断定しない。',['F488:P020']),
 ('予備のF538は生成AI利用状況・リスクの簡易点検、F541は利用状況・コスト・ガバナンス管理、F333はWeb脆弱性診断である。AIという単語が共通するだけでは同じ比較カテゴリにならない。',['F538:P001','F541:P001','F541:P002','F333:P003'])]},
'C18':{'primary':['F095','F267','F509'],'reserve':['F784','F819','F788'],'overview':'両組とも不適。完成サービスと周辺ツール・解析技術の混在。','primary_review':'不適。記事制作の一貫支援サービス2件に、文章校正・文字数計算等の無料ツール群を第三の同種サービスとして加えている。','reserve_review':'不適。特許出願書類作成・知財業務支援に、化学構造式の抽出・構造化ツールを加えており、支援する工程と選択目的が異なる。','evidence':[
 ('Uravationは画像判定・OCR・文字数・diff等の無料ツール群を提供し、文章を書く前後の作業を支援すると説明する。記事制作の一貫サービスと同じ比較単位ではない。',['F509:P001','F509:P005','F509:P006']),
 ('F788は化学文献PDFの構造式を抽出・機械可読化するWebアプリをオープンソース公開する内容である。特許出願書類作成サービスと同一目的の完成サービスとして並べない。',['F788:P001','F788:P003','F788:P034'])]},
'C19':{'primary':['F708','F722','F951'],'reserve':['F835','F748','F708'],'overview':'第一候補は無効（同一サービス重複）。予備は要再検討。','primary_review':'無効。F708とF722は同じOne Cueの共同開発・提供発表であり、3記事から3つの異なるサービスを得られていない。','reserve_review':'要再検討。研修プログラム、組織開発支援、研修後のコーチ伴走という支援段階が異なる。対象を管理職のどの課題に絞るか明確化が必要。','evidence':[
 ('F708・F722のどちらもHQとNEWONEが共同開発・提供するOne Cueを説明する。モデル自身も同サービスの別リリースと認めながらG1を合格にし、根拠表もOne CueとUMUの2列になっている。',['F708:P001','F722:P001']),
 ('予備はU-ZEROの研修本体、Zenkenの組織開発・管理職育成への支援拡充、One Cueの既存研修後3カ月の伴走であり、役割と対象課題をそろえた再検討が必要。',['F835:P001','F835:P004','F748:P001','F748:P003','F708:P002','F722:P003'])]},
'C20':{'primary':None,'reserve':None,'overview':'モデルが選定不可と判定。','reason':'農園・栽培アプリ・農地情報・ゴルフ・移住・モバイル回線などで利用目的が分散。','evidence':[]},
'C21':{'primary':['F156','F463','F578'],'reserve':['F606','F828','F625'],'overview':'第一候補は不適。予備は要再検討。','primary_review':'不適。現場のAI実装・定着支援と、既存の実装支援体制を前提とする独立した経営判断のセカンドオピニオンは、代替というより補完的な役割。','reserve_review':'要再検討。建設業の知識・設計施工支援基盤、工程表作成、汎用プロジェクト管理で範囲と役割が異なる。','evidence':[
 ('クラウドワークスとZeptはAI導入・実装・定着を支援する。プロスペリティは既存の支援体制を維持したまま経営判断を確認する第二の視点であり、AI導入は別サービスと明記する。',['F156:P003','F463:P001','F578:P003','F578:P026','F578:P027']),
 ('予備はTektomeの設計施工支援・知能基盤、Kencopaの工程表インポート・編集、Flagxsのプロジェクト管理基盤である。Flagxsの記事には考え方の提唱・デモも含まれ、提供機能を区別する必要がある。',['F606:P001','F606:P002','F828:P001','F828:P005','F625:P001','F625:P002','F625:P003'])]},
'C22':{'primary':['F730','F903','F831'],'reserve':['F730','F903','F673'],'overview':'両組とも候補として有望。提供範囲と根拠の修正は必要。','primary_review':'有望。PeopleX AI面接・Our AI面接・タレスカAI面接は法人の採用面接をAIで支援するという用途と比較単位がそろう。','reserve_review':'有望。タレスカをCareer Gateへ替えた、別の3記事組である。AI面接そのものを対象にすれば共通の選択課題を設定できる。','evidence':[
 ('PeopleXはAIによる採用面接、Our AI面接は質問・聞き取り・動画やレポート確認、タレスカはAI面接の評価と採用担当者の録画確認を説明する。Career Gateも企業の一次面接で深掘り質問・要約・スコアリングを支援する。',['F730:P013','F903:P010','F903:P013','F831:P014','F673:P002','F673:P009']),
 ('PeopleXの記事は採用プラットフォームへの拡張構想を含み、ATS連携も予定である。全機能を現行機能として比較しない。',['F730:P001','F730:P002','F730:P019']),
 ('Our AI面接の人材会社向け用途は活用想定であり、問い合わせ増加と導入実績を同一視しない。タレスカの成果は特定インターン選考の事例で、他社との同条件の比較試験ではない。',['F903:P007','F903:P011','F831:P001','F831:P004','F831:P027']),
 ('Career GateとAVITA AVATAR APIは別の提供単位である。APIの一般仕様を、そのままCareer Gateの実装済み全機能として引き継がせない。',['F673:P001','F673:P009','F673:P015','F673:P016','F673:P017'])]},
'C23':{'primary':['F308','F599','F798'],'reserve':['F930','F308','F149'],'overview':'両組とも不適。サービス独立性・比較単位に問題。','primary_review':'不適。住宅の導入事例とIoTプラットフォームの単位が混在し、Gハウスと分譲マンションのHomeLinkを別の独立サービスとして数える根拠も不足。','reserve_review':'不適。集合住宅の総合スマートホーム基盤・居住者アプリに、IoT宅配ボックスという補完機器を並べている。','evidence':[
 ('F599はGハウスの注文住宅へHomeLinkを標準搭載する発表、F798もHomeLinkを導入した分譲マンションの販売発表である。異なる住宅事例を、独立した3つのIoTサービスに数え直す根拠はない。',['F599:P001','F599:P009','F798:P001','F798:P002']),
 ('まいりむは住宅の共用部・室内機器のアプリ連携、グラモ宅配ボックスは荷物の空占有・長期占有の防止と受取・遠隔管理である。同じ読者層というだけで代替製品にはならない。',['F308:P001','F308:P003','F149:P001','F149:P002','F149:P003'])]},
'C24':{'primary':['F408','F519','F181'],'reserve':['F408','F519','F428'],'overview':'両組とも比較対象・処理環境の整理が必要。','primary_review':'条件整理が必要。現場でカメラから値を電子帳票へ入力するOCRと、紙・PDF帳票を後からデータ化するサービスで入力元・処理工程が異なる。','reserve_review':'条件整理が必要。Excel帳票を電子化する機能と、OCR結果を既存Excelテンプレートへ出力する機能を同じExcel連携として評価しない。','evidence':[
 ('XC-Gateはカメラの映像から文字・数値を読み取って電子帳票へ反映し、i-Repo EdgeOCRはラベル等の文字を現場帳票へ取り込む。paper-baseは紙・PDF等のデータ化とExcel出力である。現場の転記削減という接点はあるが、同じ作業を代替できる読取対象に絞る必要がある。',['F408:P006','F408:P007','F519:P001','F519:P009','F181:P001','F181:P002']),
 ('GenX EXCELAはOCR結果を既存のxlsxへ値だけ差し込む機能である。Excelを入力画面にする方式と、既存帳票へ出力する方式を同じ意味の比較軸にしない。',['F428:P001','F428:P003','F428:P011']),
 ('XC-Gateの本文はオンプレミス版の出荷とクラウド版の12月以降の予定を分けて記載する。モデル表のオンプレミス・クラウド併記には提供時期の注記が必要。',['F408:P001','F408:P002'])]},
'C25':{'primary':['F671','F985','F793'],'reserve':['F671','F870','F580'],'overview':'両組とも要再検討。機器カテゴリ・AI機能・装着形状に問題。','primary_review':'要再検討。イヤホンと専用ボイスレコーダーを混在させており、今回の厳格なカテゴリ一致条件ではそのまま採用しない。','reserve_review':'要再検討。オープン型イヤホンというテーマに対してHeara Airの開放型構造は本文で確認できず、AI翻訳とAI通話ノイズ抑制も同じ機能として扱えない。','evidence':[
 ('ClipBuds Pro2はオープンイヤー型イヤホン、GLIDiCはイヤホン・レコーダー・アプリの3way録音、Comulyticはスマホ背面へ装着する薄型レコーダーである。録音という共通機能だけで機器の比較カテゴリを広げている。',['F671:P001','F985:P005','F985:P006','F793:P001','F793:P004']),
 ('Comfo Bass ProのAIは通話ノイズ抑制、Heara Airは翻訳が中心。Heara Airの本文はBluetoothイヤホン形状を記載するが、耳を塞がない構造との記載は確認できない。モデルが記載なしを翻訳機能なしと断定する点も修正が必要。',['F870:P021','F870:P022','F580:P003','F580:P005','F580:P006'])]},
'C26':{'primary':None,'reserve':None,'overview':'モデルが選定不可と判定。','reason':'開発ボード、センサー、部品流通情報、光インターコネクト、ハブ、コネクタ等で対象・用途の違いを理由に候補なし。','evidence':[]},
'C27':{'primary':['F206','F278','F711'],'reserve':['F902','F711','F278'],'overview':'第一候補は粒度整理が必要。予備は有望だが機種・予定時期の固定が必要。','primary_review':'条件整理が必要。AI監視システム一式とカメラ単体で導入・比較単位が異なる。','reserve_review':'候補として有望。屋外の施設監視用ネットワークカメラという用途が近い。i-PROやAZxは複数機種があるため対象機種を固定し、i-PROは12月発売予定と明記する必要がある。','evidence':[
 ('アイパト2は検知・通知・録画に加え現場ダッシュボードや共有等を含むシステムであり、他2記事のカメラ単体と比較単位を区別する必要がある。',['F206:P001','F206:P002','F278:P001','F711:P001']),
 ('予備のi-PROは複数のネットワークカメラ、TSDは侵入検知等のあるネットワークカメラ、AZxは人物・車両検知と音光警告を備えるカメラであり、施設の警戒監視という比較用途が近い。',['F902:P001','F902:P004','F902:P008','F711:P001','F711:P002','F711:P009','F278:P001','F278:P005','F278:P007']),
 ('i-PROは計9機種の12月発売を発表しており、フリーテキスト検知は上位2機種に別売アプリを入れた場合の機能である。全モデルへ一般化しない。',['F902:P001','F902:P004'])]},
'C28':{'primary':None,'reserve':None,'overview':'モデルが選定不可と判定。','reason':'AI検索対策、3D再構成、ワークフロー、家庭ロボット、営業AI活用、コネクタ、社内チャットボットに分散。','evidence':[]},
'C29':{'primary':None,'reserve':None,'overview':'モデルが選定不可と判定。','reason':'ニュース動画生成、製造現場AI、企画支援、広告メディアプランニング、ナレッジ共有で役割が異なる。','evidence':[]},
'C30':{'primary':None,'reserve':None,'overview':'モデルが選定不可と判定。','reason':'医療分野という共通点はあるが、画像解析、集患、業務エージェント、予約、電話、AI実行基盤、栄養管理などで目的が異なる。','evidence':[]}
}

inventory={x['cluster_id']:x for x in read(OUT/'inventory.json')}
summaries=[];raws=[]
for label,review in reviews.items():
    folder=OUT/label
    articles=read(folder/'input-articles.json');by_id={a['article_id']:a for a in articles}
    raw=(folder/'selection-result.md').read_text(encoding='utf-8')
    execution=read(folder/'selection-execution.json');request=read(WORK/label/'selection-request.json')
    response=read(WORK/label/'selection-response.json');intent=read(WORK/label/'selection-intent.json')
    provenance=read(folder/'provenance.json')
    assert response['status']=='completed' and response['model']==execution['model']=='gpt-4.1-2025-04-14'
    assert len(articles)==provenance['article_count']==inventory[label]['article_count']
    assert hashlib.sha256(json.dumps(request,ensure_ascii=False).encode()).hexdigest()==intent['request_sha256']
    assert hashlib.sha256(request['input'].encode()).hexdigest()==provenance['input_sha256']
    assert hashlib.sha256(request['instructions'].encode()).hexdigest()==provenance['instructions_sha256']
    for a in articles: assert hashlib.sha256((a['title']+'\n\n'+a['body']).encode()).hexdigest()==a['input_hash']
    statuses=list(dict.fromkeys(re.findall(r'selection_status\s*[：:]\s*\**(TWO_SETS|ONE_SET|NO_SET)',raw)))
    status=statuses[0] if len(statuses)==1 else 'INCONSISTENT'
    assert statuses
    if label=='C16':assert statuses==['ONE_SET','NO_SET']
    elif review['primary'] is None:assert status=='NO_SET'
    else:
        assert status=='TWO_SETS'
        for key,heading,nextheading in [('primary','3. 第一候補','4. 予備候補'),('reserve','4. 予備候補','5. 主な不採用理由')]:
            section=raw.split(heading,1)[1].split(nextheading,1)[0]
            idline=next(line for line in section.splitlines() if '記事ID' in line)
            parsed=re.findall(r'F\d{3}',idline)
            assert parsed==review[key],(label,key,parsed)
            assert len(parsed)==len(set(parsed))==3 and set(parsed)<=set(by_id)
    for finding,refs in review['evidence']:
        for ref in refs:
            ident,para=ref.split(':');assert para in {p['paragraph_id'] for p in by_id[ident]['paragraphs']},(label,ref)
    record={'cluster_id':label,'article_count':len(articles),'body_chars':provenance['body_chars'],'combinations_requested':provenance['combinations_requested'],'raw_model_status_values':statuses,'model_status':status,'primary_ids':review['primary'],'reserve_ids':review['reserve'],'overview':review['overview'],'primary_review':review.get('primary_review'),'reserve_review':review.get('reserve_review'),'usage':execution['usage'],'generation_performed':False,'independent_evaluation_model_used':False,'all_combinations_independently_checked':False}
    if label=='C16':record['response_contract_errors']=['Header ONE_SET but conclusion NO_SET','Only two candidate articles','G1-G6 all marked failed']
    if label=='C19':record['primary_distinct_subjects']=2;record['duplicate_subject_article_ids']=['F708','F722']
    save(folder/'summary.json',record)
    save(folder/'assistant-observations.json',review)
    summaries.append(record)
    detail=[f'# {label}：全{len(articles)}記事の選定結果','',f'モデルの返答：{status}。原文内のstatus：{", ".join(statuses)}。','',f'本チャットによる確認：{review["overview"]}','']
    for key,title in [('primary','第一候補'),('reserve','予備候補')]:
        detail.extend([f'## {title}',''])
        ids=review[key]
        if ids:
            for ident in ids:
                a=by_id[ident];detail.append(f'- {ident}：[{a["title"]}]({a["url"]})')
            detail.extend(['',review[key+'_review'],''])
        else:detail.extend([review.get(key+'_review',review.get('reason','候補なし。')),''])
    if label=='C16': detail.extend(['モデルはF868・F332の2記事のみを挙げ、3件目がないと説明した。原文は修正せず保存し、1組成立とは集計しない。',''])
    if review['evidence']:
        detail.extend(['## 本文照合で確認した点',''])
        for finding,refs in review['evidence']:detail.append('- '+finding+' 根拠：'+', '.join(refs)+'。')
    else:detail.extend(['## 確認範囲','', '候補がないクラスターの理由はモデルの説明の要約である。全組み合わせの不存在を独立審査で証明したものではない。' if label!='C16' else '応答の論理・形式の不整合を確認した。補正した返答や追加のモデル呼び出しは作成していない。'])
    detail.extend(['','## 入力記事','', '| 重心順位 | 記事ID | 記事名 |','| --- | --- | --- |'])
    for a in articles:detail.append(f'| {a["centroid_rank"]} | {a["article_id"]} | [{a["title"]}]({a["url"]}) |')
    detail.extend(['','## 記録','', '- [選定モデルの返答原文](selection-result.md)','- [入力記事の全文・段落番号](input-articles.json)','- [実際に使用した指示](selection-prompt.txt)','- [モデル名・トークン数・実行時間](selection-execution.json)','- [結果JSON](summary.json)','', '本文照合はこのチャットによる主要な用途・提供段階・重複・根拠の確認であり、別モデルによる検証ではない。「有望」は入力候補としての見込みで、G1〜G6を満たす完成記事の合格ではない。今回、比較記事は生成していない。'])
    (folder/'report.md').write_text('\n'.join(detail)+'\n',encoding='utf-8')
    raws.append(f'# {label}\n\n'+raw)

counts=dict(Counter(a['model_status'] for a in summaries))
totals={'clusters':len(summaries),'articles':sum(a['article_count'] for a in summaries),'body_chars':sum(a['body_chars'] for a in summaries),'api_calls_succeeded':len(summaries),'status_counts':counts,'input_tokens':sum(a['usage']['input_tokens'] for a in summaries),'output_tokens':sum(a['usage']['output_tokens'] for a in summaries),'combinations_requested':sum(a['combinations_requested'] for a in summaries),'generation_performed':False,'independent_evaluation_model_used':False}
assert totals['clusters']==20 and totals['articles']==210 and counts=={'NO_SET':8,'TWO_SETS':11,'INCONSISTENT':1}
save(OUT/'summary.json',{'totals':totals,'clusters':summaries})
(OUT/'selection-results-all.md').write_text('\n\n---\n\n'.join(raws),encoding='utf-8')

lines=['# C11〜C30：全記事を入力したGPT-4.1の記事選定実験','', '実施日：2026年10月15日（日本時間）。','', 'C11〜C30の20クラスター、全210記事について、クラスターごとに独立してGPT-4.1へ記事選択を依頼した。11クラスターが2組、8クラスターが選定不可を返し、C16は冒頭と結論のstatusが矛盾した。API実行自体は20件すべて成功した。','', '用途・カテゴリがそろう候補として最も明確なのはC22のAI面接サービス2組、およびC13の第一候補である。C17の第一候補、C27の予備候補なども比較範囲・対象機種・提供条件を整理する余地がある。返答の比較表には根拠や提供段階の誤りがあるため、これらを完成記事の合格と扱ってはいない。','', '## 全体一覧','', '| クラスター | 全記事数 | モデル返答 | 第一候補 | 予備候補 | 本チャットの確認 |','| --- | --- | --- | --- | --- | --- |']
for a in summaries:
    lines.append(f'| [{a["cluster_id"]}]({a["cluster_id"]}/report.md) | {a["article_count"]} | {a["model_status"]} | {"・".join(a["primary_ids"] or []) or "なし"} | {"・".join(a["reserve_ids"] or []) or "なし"} | {a["overview"]} |')
lines.extend(['','C16の「なし」は正常なNO_SET応答を意味しない。冒頭ONE_SET・末尾NO_SETの矛盾と、3記事組が出力されなかったことを示す。','', '## 主な観察','', '- **C13**：みらいえAI-OCR・Facilo AI駆動コンバーター・カナリークラウドAIコンバーターは、不動産仲介の物件入力・入稿支援という用途が近い。Faciloの記事内の別プロダクトの機能を混ぜないことが必要。予備の帯替えは別工程で、モデル自身もG2を△としている。','- **C22**：PeopleX AI面接・Our AI面接・タレスカAI面接、またはタレスカをCareer Gateに替えた組である。両組ともAIによる採用面接支援という用途がそろう。ただしPeopleXの将来構想と現行機能、問い合わせ件数と導入実績、AVITA APIとCareer Gateの実装機能は区別する必要がある。','- **C17**：第一候補はAeyeScan・セルバ・SynXの脆弱性診断。診断を実現する手段には接点があるが、自動診断ツールと受託サービス、Webとモバイルの範囲を固定する必要がある。予備はAI利用リスク点検・ガバナンス管理・Web脆弱性診断の混在。','- **C27**：予備候補はi-PRO・TSD・AZxの施設監視用ネットワークカメラ。対象機種を固定し、i-PROは12月発売予定、生成AI検知は一部機種かつ別売アプリが条件であることを示す必要がある。第一候補は監視システム一式と単体カメラで比較単位が異なる。','- **C19**：第一候補のF708とF722は同じOne Cue。3記事あっても3つの異なるサービスになっていない。モデルは同一サービスと認識した記述を出しながらG1を合格にした。予備は別の3サービスだが、研修本体と研修後伴走の段階が異なり再検討が必要。','- **C16**：冒頭でONE_SET・1組と記載し、本文ではF868・F332の2件しかないとしてG1〜G6を不合格、末尾でNO_SETとする不整合応答。正常な1組にも、正常な選定不可にも自動変換していない。','- **C12・C18・C21・C23・C25**：対象者、実証・提供段階、完成サービスと補助ツール、実装支援と経営判断、同一基盤の導入事例、イヤホンとレコーダーなどの混在が見られる。個別の問題と元記事の段落は各報告に記録した。','- **C24**：OCRという共通点はあるが、現場カメラから電子帳票へ入力する方式、紙・PDFを後処理する方式、Excelテンプレートへ出力する機能で工程が異なる。XC-Gateのクラウド版も12月以降の予定で、同じ現行条件として扱わない。','', '## 実行条件','', '- 全クラスターでgpt-4.1-2025-04-14、temperature=0、store=false、max_output_tokens=16000を使用。','- 最初に提示した選定指示を継続し、記事件数と組み合わせ数だけを変更した。G1〜G6、共通比較軸3つ以上、意味のある違い2つ以上、適切な組が不足する場合に1組・0組を許す条件は同じ。','- 各クラスター全記事の本文を省略せず段落番号付きで渡した。全210件のタイトル＋空行＋本文のハッシュを保存済み埋め込みの入力ハッシュと照合した。','- 同じ所属情報を使い、クラスター内の全埋め込みの平均重心とのコサイン類似度順に全記事を表示。クラスターを横断して記事を混ぜていない。','- 過去の比較記事・選定結果・不適理由を選定モデルへ渡していない。各クラスター1回、合計20回成功。再プロンプト・再選定を行っていない。','- 比較記事の生成、別モデルによる評価、全組み合わせの独立した再審査は実施していない。','', '| クラスター | 記事数 | 本文文字数 | 検討を指示した組数 | 入力トークン | 出力トークン |','| --- | --- | --- | --- | --- | --- |'])
for a in summaries:lines.append(f'| {a["cluster_id"]} | {a["article_count"]} | {a["body_chars"]:,} | {a["combinations_requested"]:,} | {a["usage"]["input_tokens"]:,} | {a["usage"]["output_tokens"]:,} |')
lines.extend([f'| 合計 | {totals["articles"]} | {totals["body_chars"]:,} | {totals["combinations_requested"]:,} | {totals["input_tokens"]:,} | {totals["output_tokens"]:,} |','', '## 解釈上の範囲','', '上の確認は、このチャットが元記事の主要な用途・比較単位・提供段階・重複・明示的な不整合を照合したものである。返答に含まれる全比較軸・全数値を独立に完全検証したという意味ではない。「有望」は次の生成実験への入力候補であり、G1〜G6や完成記事の最終合格ではない。','', 'NO_SETは今回のモデルが適切な3記事組を返さなかったという結果であり、当該クラスターに適切な組が存在しないことの証明ではない。モデルには全組み合わせの検討を指示したが、全組の判定表は返されておらず、内部での網羅的検討は確認できない。候補のないクラスターの理由はモデルの説明を要約している。','', '## 記録','', '- [20クラスターの選定結果原文](selection-results-all.md)','- [機械可読の結果一覧](summary.json)',''])
for a in summaries:lines.append(f'- [{a["cluster_id"]}の報告]({a["cluster_id"]}/report.md) ／ [選定原文]({a["cluster_id"]}/selection-result.md)')
(OUT/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'validated':True,'totals':totals,'report':str(OUT/'report.md'),'inconsistent_response':'C16','duplicate_service':'C19 primary','most_promising':['C22 primary','C22 reserve','C13 primary']},ensure_ascii=False))
