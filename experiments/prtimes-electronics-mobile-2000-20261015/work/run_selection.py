"""Run current NewsWeave through selection, with real API call receipts."""
import sys,re,json,hashlib,sqlite3
from pathlib import Path
from datetime import datetime,UTC
sys.path.insert(0,str(Path(__file__).parent/'runtime'))
from sqlalchemy import select,func
from app.db import open_session
from app.models import Article,Run,RunArticle,Comparison,Draft,Verification
from app.pipeline import Pipeline,validate_selection
from app.model_client import OpenAI
from app.settings import Settings
from app.clustering import selection_candidates

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'
DB=OUT/'newsweave-electronics-mobile-2000-20261015.sqlite'

def log(**data):
    data={'time':datetime.now(UTC).isoformat(),**data}
    line=json.dumps(data,ensure_ascii=False)
    with (OUT/'model-progress.jsonl').open('a',encoding='utf-8') as f:f.write(line+'\n')
    print(line,flush=True)

class AuditedOpenAI(OpenAI):
    def post(self,endpoint,payload):
        stamp=datetime.now(UTC).isoformat()
        result=super().post(endpoint,payload)
        record={'requested_at':stamp,'completed_at':datetime.now(UTC).isoformat(),'endpoint':endpoint,
                'model_requested':payload.get('model'),'model_returned':result.get('model'),
                'response_id':result.get('id'),'status':result.get('status'),
                'usage':result.get('usage'),
                'request_sha256':hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
        if endpoint=='responses':
            data=json.loads(payload['input']);label=data['cluster_id']
            record['cluster_id']=label
            folder=OUT/'model-io';folder.mkdir(exist_ok=True)
            (folder/f'cluster-{label:03d}-request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            (folder/f'cluster-{label:03d}-response.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            receipt=hashlib.sha256(str(result.get('id',record['request_sha256'])).encode()).hexdigest()[:16]
            for kind,value in [('request',payload),('response',result)]:
                (folder/f'cluster-{label:03d}-attempt-{receipt}-{kind}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
            log(stage='selection_response',cluster_id=label,model=result.get('model'),status=result.get('status'))
        with (OUT/'api-calls.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
        if endpoint=='embeddings':
            self.embedded=getattr(self,'embedded',0)+1
            if self.embedded%25==0:log(stage='embedding',completed_this_process=self.embedded)
        return result

def provider():
    # Load only the one authorized API credential. Never copy the .env file.
    path=Path(r'\\TRUENAS\dev\codex\newsWeave\.env')
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        match=re.match(r'^AI_API_KEY=(.*)$',line)
        if match:return AuditedOpenAI(key=match[1].strip().strip('"').strip("'"))
    raise ValueError('API_KEY_REQUIRED')

def main():
    session=open_session('sqlite:///'+DB.as_posix())
    count=session.scalar(select(func.count()).select_from(Article))
    if count!=2000:raise ValueError(f'ARTICLE_TARGET_NOT_MET:{count}')
    client=provider();pipeline=Pipeline(session,client)
    run=session.scalar(select(Run).order_by(Run.created_at.desc()).limit(1))
    if run is None:run=pipeline.start(Settings())
    manifest={'database':str(DB),'database_url':'sqlite:///'+DB.as_posix(),'run_id':run.id,
              'target_articles':2000,'keywords':['電子工作','モバイル'],
              'require_ai_iot':False,'release_type':'01','title_exclusions':'app/title-exclusions.txt',
              'selection_model':Settings.selection_model,'stop_after':'select',
              'settings':{k:v for k,v in run.settings.items() if k!='prompts'}}
    (OUT/'run-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    log(stage='run_start_or_resume',run_id=run.id,step=run.step,articles=count,
        latest_company_articles=session.scalar(select(func.count()).select_from(RunArticle)))
    try:run=pipeline.process(run.id,stop_after='select')
    except Exception as exc:
        log(stage='run_error',error_type=type(exc).__name__,error_code=str(exc) if isinstance(exc,ValueError) else 'transport_or_runtime')
        raise
    finally:client.close()
    export(session,run,manifest)
    session.close()

def export(session,run,manifest):
    assert run.step=='generate' and run.error is None
    assert session.scalar(select(func.count()).select_from(Draft))==0
    assert session.scalar(select(func.count()).select_from(Verification))==0
    members=Pipeline(session,None).members(run)
    articles={a.id:a for _,a in members}
    groups={}
    for row,a in members:
        if row.cluster_id>=0:groups.setdefault(row.cluster_id,[]).append((a.id,a.url,row.embedding))
    comparisons=list(session.scalars(select(Comparison).where(Comparison.run_id==run.id).order_by(Comparison.cluster_id)))
    assert len(comparisons)==len([g for g in groups.values() if len(g)>=3])
    result=[]
    for c in comparisons:
        assert c.candidate_article_ids==selection_candidates(groups[c.cluster_id],30)
        validate_selection(c.selection_result,c.candidate_article_ids)
        record={'cluster_id':c.cluster_id,'cluster_size':len(groups[c.cluster_id]),
                'candidate_article_ids':c.candidate_article_ids,'selection':c.selection_result}
        for role in ['PRIMARY','RESERVE']:
            record[role.lower()]=[{'article_id':i,'title':articles[i].title,'url':articles[i].url,
                  'company_id':articles[i].company_id,'published_at':articles[i].published_at} for i in c.source_ids(role)]
        result.append(record)
    statuses={s:sum(c.selection_result['selection_status']==s for c in comparisons) for s in ['TWO_SETS','ONE_SET','NO_SET']}
    manifest.update({'step':run.step,'selection_complete':True,'article_count':2000,
       'latest_company_articles':len(members),'noise_articles':sum(row.cluster_id==-1 for row,_ in members),
       'clusters':len(groups),'selection_results':statuses,'drafts':0,'verifications':0,
       'completed_at':datetime.now(UTC).isoformat()})
    (OUT/'run-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'selections.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 本命・予備の選定結果','',f'実行ID: `{run.id}`。GPT-4.1による選定完了。比較記事生成は未実行。','',
           f'適格記事2,000件 → 企業ごとの最新記事{len(members)}件 → {len(groups)}クラスター（ノイズ{manifest["noise_articles"]}件）。',
           '',f'2組選定: {statuses["TWO_SETS"]}、本命のみ: {statuses["ONE_SET"]}、選定不可: {statuses["NO_SET"]}。','']
    for r in result:
        lines.extend([f'## クラスター {r["cluster_id"]:03d}',f'所属{r["cluster_size"]}件、選定候補{len(r["candidate_article_ids"])}件。判定: `{r["selection"]["selection_status"]}`。',''])
        for role,label in [('primary','本命'),('reserve','予備')]:
            lines.extend([f'### {label}',''])
            lines.extend([f'- [{a["title"].replace("[","（").replace("]","）").replace(chr(10)," ")}]({a["url"]})（{a["company_id"]}、{a["published_at"]}）' for a in r[role]] or ['該当なし。'])
            lines.append('')
        lines.extend(['### モデルの選定理由','',r['selection']['reason'],''])
    (OUT/'selections.md').write_text('\n'.join(lines).replace('\x00',''),encoding='utf-8')
    log(stage='selection_complete',**manifest)

if __name__=='__main__':main()
