import hashlib
import json
import math
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

BASE = Path(__file__).resolve().parents[1]
WORK = BASE / 'work' / 'c01-trial'
WORK.mkdir(exist_ok=True)
ROOT = Path(r'\\TRUENAS\dev\codex\newsWeave')

def save(name, value):
    (WORK/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def prepare():
    source = ROOT/'.local/seven-stage-real-c01-20261015/cluster-input.json'
    records=json.loads(source.read_text(encoding='utf-8-sig'))
    assert len(records)==13
    vectors=[]
    for r in records:
        a=r['article']
        assert hashlib.sha256((a['title']+'\n\n'+a['body']).encode()).hexdigest()==r['input_hash']
        v=r['embedding']
        norm=math.sqrt(sum(x*x for x in v))
        assert norm>0 and all(math.isfinite(x) for x in v)
        vectors.append([x/norm for x in v])
    center=[sum(v[i] for v in vectors)/len(vectors) for i in range(len(vectors[0]))]
    cn=math.sqrt(sum(x*x for x in center))
    ranks=sorted([(sum(x*y for x,y in zip(v,center))/cn,r['article']) for v,r in zip(vectors,records)],key=lambda t:(-t[0],t[1]['id']))
    baseline=json.loads((ROOT/'.local/model-comparison-c01-c10-20261015/sources/C01.json').read_text(encoding='utf-8-sig'))
    assert [a['id'] for _,a in ranks[:3]]==baseline['source_ids']
    rows=[]
    for i,(score,a) in enumerate(ranks,1):
        rows.append({'article_id':a['id'],'centroid_rank':i,'cosine_similarity':score,'cosine_distance':1-score,'title':a['title'],'url':a['url'],'published_at':a['published_at'],'body_chars':len(a['body'])})
    selected=[]
    for row,(_,a) in zip(rows[:7],ranks[:7]):
        paragraphs=[{'paragraph_id':f'P{i:03d}','text':s} for i,s in enumerate(a['body'].split('\n\n'),1)]
        selected.append({**row,'body':a['body'],'paragraphs':paragraphs,'body_sha256':hashlib.sha256(a['body'].encode()).hexdigest()})
    save('ranking-all13.json',rows)
    save('input-seven.json',selected)
    xml=['cluster_id：C01','クラスター概要：未提供','<articles>']
    for a in selected:
        xml.extend([f'<article id="{a["article_id"]}" centroid_rank="{a["centroid_rank"]}">',f'<title>{escape(a["title"])}</title>',f'<url>{escape(a["url"])}</url>',f'<published_at>{escape(a["published_at"])}</published_at>','<body>'])
        xml.extend(f'[{p["paragraph_id"]}] {escape(p["text"])}' for p in a['paragraphs'])
        xml.extend(['</body>','</article>'])
    xml.append('</articles>')
    input_text='\n'.join(xml)
    (WORK/'input-seven.xml').write_text(input_text,encoding='utf-8')
    prompt=(BASE/'work/c01-selection-prompt.txt').read_text(encoding='utf-8')
    payload={'model':'gpt-4.1-2025-04-14','instructions':prompt,'input':input_text,'store':False,'max_output_tokens':16000,'temperature':0}
    save('selection-request.json',payload)
    save('provenance.json',{'created_at':datetime.now(timezone.utc).isoformat(),'cluster_id':'C01','cluster_members':13,'k':7,'source_snapshot':str(source),'baseline_source_ids':baseline['source_ids'],'selection_model':payload['model'],'generation_model':'current_chat_assistant','previous_generated_articles_or_verdicts_used_for_selection':False,'centroid_definition':'L2-normalize all 13 original embeddings; arithmetic mean; normalize centroid; descending cosine similarity','verified_source_hashes':13,'instructions_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'input_sha256':hashlib.sha256(input_text.encode()).hexdigest()})
    print(json.dumps({'prepared':True,'input_body_chars':sum(a['body_chars'] for a in selected),'article_ids':[a['article_id'] for a in selected]},ensure_ascii=False))

def api_key():
    val=os.getenv('OPENAI_API_KEY') or os.getenv('AI_API_KEY')
    if val:return val
    for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
        if line.startswith(('AI_API_KEY=','OPENAI_API_KEY=')):
            val=line.split('=',1)[1].strip().strip('"').strip("'")
            if val:return val
    raise RuntimeError('API_KEY_REQUIRED')

def call():
    assert not (WORK/'selection-response.json').exists(),'Response already exists'
    if (WORK/'selection-intent.json').exists() and (WORK/'selection-error.json').exists():
        prior=json.loads((WORK/'selection-error.json').read_text(encoding='utf-8'))
        if prior=={'kind':'URLError','reason_type':'gaierror'}:
            # DNS resolution failed before a connection or API request could be sent.
            (WORK/'selection-intent.json').rename(WORK/'selection-intent-dns-failed.json')
            (WORK/'selection-error.json').rename(WORK/'selection-error-dns-failed.json')
    assert not (WORK/'selection-intent.json').exists(),'Prior attempt must be inspected before any retry'
    payload=json.loads((WORK/'selection-request.json').read_text(encoding='utf-8'))
    data=json.dumps(payload,ensure_ascii=False).encode()
    req=urllib.request.Request('https://api.openai.com/v1/responses',data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+api_key()},method='POST')
    save('selection-intent.json',{'started_at':datetime.now(timezone.utc).isoformat(),'model':payload['model'],'request_sha256':hashlib.sha256(data).hexdigest()})
    print('Selection API request started',flush=True)
    start=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=300) as response:
            result=json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        err=json.loads(e.read().decode())
        save('selection-error.json',{'kind':'HTTPError','http_status':e.code,'error_code':err.get('error',{}).get('code')})
        print('HTTP_ERROR',e.code,err.get('error',{}).get('code'),flush=True)
        raise SystemExit(2)
    except Exception as e:
        save('selection-error.json',{'kind':type(e).__name__,'reason_type':type(getattr(e,'reason',None)).__name__})
        print('TRANSPORT_ERROR',type(e).__name__,flush=True)
        raise SystemExit(3)
    save('selection-response.json',result)
    assert result.get('status')=='completed',result.get('status')
    text=''.join(c['text'] for o in result.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text')
    assert text
    (WORK/'selection-result.md').write_text(text+'\n',encoding='utf-8')
    save('selection-execution.json',{'elapsed_seconds':time.monotonic()-start,'response_id':result['id'],'model':result['model'],'status':result['status'],'usage':result.get('usage')})
    print(json.dumps({'completed':True,'model':result['model'],'usage':result.get('usage'),'output_chars':len(text)},ensure_ascii=False),flush=True)

if __name__=='__main__':
    {'prepare':prepare,'call':call}[sys.argv[1]]()
