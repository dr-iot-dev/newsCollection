import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from c01_trial import api_key

BASE=Path(__file__).resolve().parents[1]
WORK=BASE/'work/c02-all11-trial'
OUT=BASE/'outputs/C02-all11-selection-20261015'
ROOT=Path(r'\\TRUENAS\dev\codex\newsWeave')
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

def save(name,value):
    (WORK/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def prepare():
    path=ROOT/'.local/seven-stage-real-c02-fresh-20261015/cluster-input.json'
    records=json.loads(path.read_text(encoding='utf-8-sig'))
    assert len(records)==11
    vectors=[]
    for r in records:
        a=r['article']
        assert hashlib.sha256((a['title']+'\n\n'+a['body']).encode()).hexdigest()==a['snapshot_hash']
        v=r['embedding']; norm=math.sqrt(sum(x*x for x in v))
        assert norm>0 and all(math.isfinite(x) for x in v)
        vectors.append([x/norm for x in v])
    center=[sum(v[i] for v in vectors)/len(vectors) for i in range(len(vectors[0]))]
    norm=math.sqrt(sum(x*x for x in center))
    ranks=sorted([(sum(x*y for x,y in zip(v,center))/norm,r['article']) for v,r in zip(vectors,records)],key=lambda t:(-t[0],t[1]['id']))
    inputs=[]
    for i,(score,a) in enumerate(ranks,1):
        paragraphs=[{'paragraph_id':f'P{j:03d}','text':p} for j,p in enumerate(a['body'].split('\n\n'),1)]
        inputs.append({'article_id':a['id'],'centroid_rank':i,'cosine_similarity':score,'cosine_distance':1-score,'title':a['title'],'url':a['url'],'published_at':a['published_at'],'body_chars':len(a['body']),'body':a['body'],'paragraphs':paragraphs,'snapshot_hash':a['snapshot_hash']})
    old_prompt=(BASE/'work/c01-selection-prompt.txt').read_text(encoding='utf-8')
    prompt=old_prompt.replace('7記事','11記事').replace('全35通り','全165通り')
    assert math.comb(len(inputs),3)==165
    (WORK/'selection-prompt.txt').write_text(prompt,encoding='utf-8')
    xml=['cluster_id：C02','クラスター概要：未提供','入力範囲：C02に所属する全11記事。重心に近い順に表示する。','<articles>']
    for a in inputs:
        xml.extend([f'<article id="{a["article_id"]}" centroid_rank="{a["centroid_rank"]}">',f'<title>{escape(a["title"])}</title>',f'<url>{escape(a["url"])}</url>',f'<published_at>{escape(a["published_at"])}</published_at>','<body>'])
        xml.extend(f'[{p["paragraph_id"]}] {escape(p["text"])}' for p in a['paragraphs'])
        xml.extend(['</body>','</article>'])
    xml.append('</articles>')
    text='\n'.join(xml)
    (WORK/'input-all11.xml').write_text(text,encoding='utf-8')
    save('input-all11.json',inputs)
    save('selection-request.json',{'model':'gpt-4.1-2025-04-14','instructions':prompt,'input':text,'temperature':0,'store':False,'max_output_tokens':16000})
    save('provenance.json',{'cluster_id':'C02','articles':11,'combination_count':165,'input_body_chars':sum(a['body_chars'] for a in inputs),'model':'gpt-4.1-2025-04-14','temperature':0,'prompt_changes_from_initial_trial':['7記事 -> 11記事','全35通り -> 全165通り'],'previous_model_outputs_in_selector_input':False,'source_snapshot':str(path),'source_hashes_verified':11,'centroid_definition':'L2-normalize all 11 original embeddings; arithmetic mean; normalize centroid; descending cosine similarity','input_sha256':hashlib.sha256(text.encode()).hexdigest(),'instructions_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'created_at':datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'prepared':True,'articles':len(inputs),'body_chars':sum(a['body_chars'] for a in inputs),'candidate_combinations':165,'article_ids':[a['article_id'] for a in inputs]},ensure_ascii=False))

def call():
    assert not (WORK/'selection-intent.json').exists(),'Do not duplicate a potentially sent request'
    payload=json.loads((WORK/'selection-request.json').read_text(encoding='utf-8'))
    data=json.dumps(payload,ensure_ascii=False).encode()
    request=urllib.request.Request('https://api.openai.com/v1/responses',data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+api_key()},method='POST')
    save('selection-intent.json',{'started_at':datetime.now(timezone.utc).isoformat(),'model':payload['model'],'request_sha256':hashlib.sha256(data).hexdigest()})
    start=time.monotonic()
    print('GPT-4.1 C02 all-11-article selection request started',flush=True)
    try:
        with urllib.request.urlopen(request,timeout=300) as response:
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
    assert result['status']=='completed',result['status']
    answer=''.join(c['text'] for o in result.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text')
    assert answer
    (WORK/'selection-result.md').write_text(answer+'\n',encoding='utf-8')
    save('selection-execution.json',{'elapsed_seconds':time.monotonic()-start,'response_id':result['id'],'model':result['model'],'status':result['status'],'usage':result.get('usage')})
    for name in ['selection-result.md','selection-execution.json','selection-prompt.txt','input-all11.json','input-all11.xml','provenance.json']:
        (OUT/name).write_bytes((WORK/name).read_bytes())
    print(json.dumps({'completed':True,'model':result['model'],'usage':result.get('usage'),'output_chars':len(answer)},ensure_ascii=False),flush=True)

if __name__=='__main__':
    {'prepare':prepare,'call':call}[sys.argv[1]]()
