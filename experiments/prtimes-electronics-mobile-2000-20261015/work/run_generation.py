"""Continue saved selection using Sol generation and Astra independent verification."""
import argparse,copy,hashlib,json,re,sqlite3,sys,time
from pathlib import Path
from datetime import datetime,UTC
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).parent/'runtime'))
import httpx
from sqlalchemy import select,func
from app.db import open_session
from app.models import Run,RunArticle,Comparison,Draft,Verification,Article
from app.pipeline import Pipeline
from app.model_client import OpenAI
from app.settings import Settings
from cost_measurement import measure,write_reports,ledger

ROOT=Path(__file__).resolve().parents[1];PARENT=ROOT/'outputs'
OUT=PARENT/'generation-sol-astra-20261015';DB=OUT/'generation.sqlite'
SOURCE=PARENT/'newsweave-electronics-mobile-2000-20261015.sqlite'
GENERATOR='gpt-6.1-sol';VERIFIER='gpt-6-astra'

def hash_file(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def save_json(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def log(**value):
    value={'time':datetime.now(UTC).isoformat(),**value};line=json.dumps(value,ensure_ascii=False)
    with (OUT/'progress.jsonl').open('a',encoding='utf-8') as f:f.write(line+'\n')
    print(line,flush=True)

def prepare():
    OUT.mkdir(exist_ok=True)
    manifest_path=OUT/'run-manifest.json'
    if manifest_path.exists():return json.loads(manifest_path.read_text(encoding='utf-8'))
    if DB.exists():raise ValueError('UNREGISTERED_GENERATION_DATABASE')
    parent_manifest=json.loads((PARENT/'run-manifest.json').read_text(encoding='utf-8'))
    source_hash=hash_file(SOURCE)
    source=sqlite3.connect('file:'+SOURCE.as_posix()+'?mode=ro',uri=True)
    target=sqlite3.connect(DB);source.backup(target);target.close();source.close()
    with open_session('sqlite:///'+DB.as_posix()) as session:
        old=session.get(Run,parent_manifest['run_id'])
        assert old.step=='generate' and old.error is None
        settings=copy.deepcopy(old.settings);settings['generation_model']=GENERATOR;settings['verification_model']=VERIFIER
        Settings(**{k:v for k,v in settings.items() if k!='prompts'}).validate()
        new=Run(settings=settings,step='generate',error=None);session.add(new);session.flush()
        for row in session.scalars(select(RunArticle).where(RunArticle.run_id==old.id)):
            session.add(RunArticle(run_id=new.id,article_id=row.article_id,embedding=copy.deepcopy(row.embedding),cluster_id=row.cluster_id))
        session.flush();mapping={}
        for c in session.scalars(select(Comparison).where(Comparison.run_id==old.id)):
            data={field:copy.deepcopy(getattr(c,field)) for field in ['cluster_id','source1','source2','source3','reserve1','reserve2','reserve3','candidate_article_ids','selection_result']}
            clone=Comparison(run_id=new.id,**data);session.add(clone);session.flush();mapping[c.id]=clone.id
        session.commit()
        manifest={'database':str(DB),'database_url':'sqlite:///'+DB.as_posix(),'run_id':new.id,
          'parent_selection_database':str(SOURCE),'parent_selection_database_sha256':source_hash,'parent_selection_run_id':old.id,
          'comparison_id_mapping':mapping,'generation_model':GENERATOR,'verification_model':VERIFIER,
          'reasoning_effort':'medium','max_output_tokens':32000,'service_tier':'default',
          'generation_instructions_sha256':hashlib.sha256(settings['prompts']['generation'].encode()).hexdigest(),
          'verification_instructions_sha256':hashlib.sha256(settings['prompts']['verification'].encode()).hexdigest(),
          'state':'prepared','created_at':datetime.now(UTC).isoformat()}
    save_json(manifest_path,manifest)
    write_reports(OUT,PARENT/'api-calls.jsonl')
    log(stage='prepared',run_id=manifest['run_id'],generation_model=GENERATOR,verification_model=VERIFIER)
    return manifest

def key():
    for line in Path(r'\\TRUENAS\dev\codex\newsWeave\.env').read_text(encoding='utf-8-sig').splitlines():
        match=re.match(r'^AI_API_KEY=(.*)$',line)
        if match:return match[1].strip().strip('"').strip("'")
    raise ValueError('API_KEY_REQUIRED')

class MeteredProvider(OpenAI):
    def __init__(self,session,run):
        super().__init__(key=key());self.client.timeout=httpx.Timeout(600,connect=30)
        self.session=session;self.context={}
        for c in session.scalars(select(Comparison).where(Comparison.run_id==run.id)):
            for role in ['PRIMARY','RESERVE']:
                ids=c.source_ids(role)
                if ids:
                    urls=tuple(session.get(Article,i).url for i in ids)
                    self.context[urls]={'cluster_id':c.cluster_id,'comparison_id':c.id,'set_role':role}

    def post(self,endpoint,payload):
        model=payload.get('model')
        if endpoint!='responses' or model not in [GENERATOR,VERIFIER]:raise ValueError('UNEXPECTED_MODEL_STAGE')
        payload={**payload,'reasoning':{'effort':'medium'},'max_output_tokens':32000,'service_tier':'default'}
        data=json.loads(payload['input']);context=self.context[tuple(s['url'] for s in data['sources'])]
        verification=model==VERIFIER
        revision=1 if 'feedback' in data else 0
        if verification:
            revision=self.session.scalar(select(func.max(Draft.revision)).where(Draft.comparison_id==context['comparison_id'],Draft.set_role==context['set_role'])) or 0
        operation=('reverification' if revision else 'verification') if verification else ('repair' if revision else 'generation')
        call_id=str(uuid4());folder=OUT/'calls';folder.mkdir(exist_ok=True)
        request_name=f'{call_id}-request.json';response_name=f'{call_id}-response.json'
        save_json(folder/request_name,payload)
        record={'call_id':call_id,'requested_at':datetime.now(UTC).isoformat(),'endpoint':endpoint,
          'model_requested':model,'operation':operation,'revision':revision,**context,
          'request_file':'calls/'+request_name,'response_file':'calls/'+response_name,
          'request_sha256':hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
        log(stage='api_request',operation=operation,model=model,cluster_id=context['cluster_id'],set_role=context['set_role'],revision=revision)
        started=time.monotonic()
        try:
            result=super().post(endpoint,payload);save_json(folder/response_name,result)
        except Exception as exc:
            record.update({'completed_at':datetime.now(UTC).isoformat(),'elapsed_seconds':round(time.monotonic()-started,3),
              'usage':None,'error_type':type(exc).__name__,'error_code':str(exc) if isinstance(exc,ValueError) else 'TRANSPORT_ERROR'})
            self.receipt(record);raise
        record.update({'completed_at':datetime.now(UTC).isoformat(),'elapsed_seconds':round(time.monotonic()-started,3),
          'response_id':result.get('id'),'model_returned':result.get('model'),'status':result.get('status'),
          'usage':result.get('usage'),'service_tier':result.get('service_tier','default')})
        record['cost']=measure(model,record['usage'],record['service_tier'])
        self.receipt(record)
        verdict={}
        try:verdict=json.loads(''.join(x['text'] for o in result.get('output',[]) for x in o.get('content',[]) if x.get('type')=='output_text'))
        except (ValueError,KeyError):pass
        log(stage='api_response',operation=operation,model=result.get('model'),cluster_id=context['cluster_id'],set_role=context['set_role'],
            revision=revision,response_status=result.get('status'),verdict=verdict.get('status'),score=verdict.get('score'),cost_usd=record['cost']['cost_usd'])
        if result.get('model')!=model:raise ValueError('MODEL_ID_MISMATCH')
        return result

    def receipt(self,record):
        with (OUT/'api-calls.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
        write_reports(OUT,PARENT/'api-calls.jsonl')

def export(session,run,manifest):
    result=Pipeline(session,None).export(run.id,OUT/'articles')
    receipts=ledger(OUT/'api-calls.jsonl')
    error_code=receipts[-1].get('error_code') if run.error and receipts else None
    completed_models=__import__('collections').Counter(r.get('model_returned') for r in receipts if r.get('status')=='completed')
    manifest.update({'state':run.step,'error':run.error,'updated_at':datetime.now(UTC).isoformat(),
        'error_code':error_code,'execution_status':'blocked_api_credit' if error_code and 'credit_balance_exhausted' in error_code else 'complete' if run.step=='complete' else 'incomplete',
        'completed_api_responses_by_model':dict(completed_models),
        'final_status_counts':dict(__import__('collections').Counter(r['status'] or 'pending' for r in result['articles'])),
        'final_generation_counts':dict(__import__('collections').Counter(r['generation_status'] or 'not_selected' for r in result['articles']))})
    save_json(OUT/'run-manifest.json',manifest)
    costs=write_reports(OUT,PARENT/'api-calls.jsonl')
    lines=['# Sol生成・Astra検証の結果','',f'実行ID: `{run.id}`。状態: `{run.step}`。','',
      '生成: `gpt-6.1-sol`、独立検証: `gpt-6-astra`。両モデルの推論設定はmedium。','',
      '選定済みの本命15組を対象に、本命の生成不適時のみ選定済み予備を試行する。生成できた記事は独立検証を受け、不適・要確認なら同じ3原資料で1回だけ修正・再検証する。','',
      '| クラスター | 使用組 | 最終生成判定 | 最終検証 | 点数 | 本文・不適理由 |',
      '| --- | --- | --- | --- | ---: | --- |']
    if error_code:
        lines[2:2]=[f'**中断中: `{error_code}`。**',f'完了API応答: Sol {completed_models[GENERATOR]}件、Astra {completed_models[VERIFIER]}件。生成済みでも検証待ちの記事は採用確定ではない。','']
    for row in result['articles']:
        filename=row['article'] or row['inappropriate_report'];link=f'[開く](articles/{filename})' if filename else '—'
        status='選定不可' if row['status']=='not_selected' else '生成不適・未検証' if row['generation_status']=='INAPPROPRIATE' else row['status'] or ('検証待ち' if row['generation_status']=='APPROPRIATE' else '未着手')
        lines.append(f'| {row["cluster_id"]:03d} | {row["set_role"]} | {row["generation_status"] or "—"} | {status} | {row["score"] if row["score"] is not None else "—"} | {link} |')
    lines+=['',f'今回の生成・検証費用: **${costs["generation_verification_cost_usd"]}**（API使用量×公開単価）。[モデル別・工程別コスト](costs.md)。','',
      '検証の判定・点数・理由、予備への切替、初稿・修正版の履歴は[機械可読結果](articles/results.json)と[全履歴](history.json)に保存する。',
      '生成・検証の要求と応答は`calls/`、使用量とモデルIDは`api-calls.jsonl`へ保存する。','',
      '選定元DBは保持し、新しい生成用DBへ原資料・埋め込み・選定結果をコピーした。新しい実行IDを割り当て、選定や埋め込みのAPIは再実行していない。']
    for row in result['articles']:
        if row['status']=='not_selected':continue
        lines+=['',f'## クラスター {row["cluster_id"]:03d} の最終理由','',row['reason'] or ('生成済み。独立検証待ち。' if row['generation_status']=='APPROPRIATE' else '生成未着手。')]
    (OUT/'report.md').write_text('\n'.join(lines).replace('\x00',''),encoding='utf-8')
    history=[]
    for c in session.scalars(select(Comparison).where(Comparison.run_id==run.id).order_by(Comparison.cluster_id)):
        for d in session.scalars(select(Draft).where(Draft.comparison_id==c.id).order_by(Draft.set_role,Draft.revision)):
            v=session.get(Verification,d.id)
            history.append({'cluster_id':c.cluster_id,'draft_id':d.id,'set_role':d.set_role,'revision':d.revision,
              'generation_status':d.generation_status,'generation_reason':d.generation_reason,'article_markdown':d.markdown,
              'verification':{'status':v.status,'score':v.score,'reason':v.reason} if v else None})
    save_json(OUT/'history.json',history)
    if run.step=='complete':
        assert hash_file(SOURCE)==manifest['parent_selection_database_sha256']
        assert all(r['status'] is not None for r in result['articles'])
        raw=sqlite3.connect(DB)
        assert raw.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert not raw.execute('pragma foreign_key_check').fetchall();raw.close()
        save_json(OUT/'verification.json',{'state':'complete','database_integrity':'ok','foreign_keys':'ok','selection_source_unchanged':True,
          'run_id':run.id,'checked_at':datetime.now(UTC).isoformat()})
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    manifest=prepare()
    if args.prepare:return
    with open_session('sqlite:///'+DB.as_posix()) as session:
        run=session.get(Run,manifest['run_id']);client=MeteredProvider(session,run)
        try:
            log(stage='run_start_or_resume',run_id=run.id,step=run.step)
            Pipeline(session,client).process(run.id)
        finally:
            client.close();session.expire_all();run=session.get(Run,manifest['run_id']);export(session,run,manifest)
        log(stage='generation_verification_complete',run_id=run.id,step=run.step)

if __name__=='__main__':main()
