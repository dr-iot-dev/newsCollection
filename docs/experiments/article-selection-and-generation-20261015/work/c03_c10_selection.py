import concurrent.futures
import hashlib
import json
import math
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from c01_trial import api_key

BASE=Path(__file__).resolve().parents[1]
ROOT=Path(r'\\TRUENAS\dev\codex\newsWeave')
WORK=BASE/'work/c03-c10-allarticles-trial'
OUT=BASE/'outputs/C03-C10-allarticles-selection-20261015'
CLUSTERS=[f'C{i:02d}' for i in range(3,11)]
LOCK=threading.Lock()
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def prepare():
    assignments=read(ROOT/'.local/extraction-organization-latest-20261013/cores/article-clusters.json')['articles']
    vectors={a['article_id']:a for a in read(ROOT/'.local/extraction-organization-latest-20261013/selection/article-values.json')['articles']}
    original_prompt=(BASE/'work/c01-selection-prompt.txt').read_text(encoding='utf-8')
    name=(ROOT/'.local/extraction-1000-20261013/iot-articles.sqlite').resolve().as_posix()
    uri='file:'+('//' if name.startswith('//') else '')+quote(name,safe='/:')+'?mode=ro'
    inventory=[]
    with sqlite3.connect(uri,uri=True) as database:
        database.row_factory=sqlite3.Row
        for label in CLUSTERS:
            folder=WORK/label;folder.mkdir(exist_ok=True)
            delivery=OUT/label;delivery.mkdir(exist_ok=True)
            members=[a for a in assignments if a['cluster_id']==label]
            records=[]
            values=[]
            for member in members:
                vector=vectors[member['article_id']]
                source=database.execute('SELECT title,body,url FROM term_articles WHERE article_id=?',(member['article_id'],)).fetchone()
                assert source is not None
                assert hashlib.sha256((source['title']+'\n\n'+source['body']).encode()).hexdigest()==vector['input_hash']
                v=vector['value'];norm=math.sqrt(sum(x*x for x in v))
                assert norm>0 and all(math.isfinite(x) for x in v)
                values.append([x/norm for x in v])
                records.append({'article_id':vector['f_id'],'title':source['title'],'url':source['url'],'published_at':vector['published_at_utc'],'body':source['body'],'body_chars':len(source['body']),'input_hash':vector['input_hash']})
            assert len(records)>=3 and len({a['article_id'] for a in records})==len(records)
            center=[sum(v[i] for v in values)/len(values) for i in range(len(values[0]))]
            norm=math.sqrt(sum(x*x for x in center))
            ordered=sorted([(sum(x*y for x,y in zip(v,center))/norm,a) for v,a in zip(values,records)],key=lambda t:(-t[0],t[1]['article_id']))
            articles=[]
            for rank,(score,a) in enumerate(ordered,1):
                articles.append({**a,'centroid_rank':rank,'cosine_similarity':score,'paragraphs':[{'paragraph_id':f'P{i:03d}','text':p} for i,p in enumerate(a['body'].split('\n\n'),1)]})
            count=len(articles);combinations=math.comb(count,3)
            prompt=original_prompt.replace('7記事',f'{count}記事').replace('全35通り',f'全{combinations}通り')
            xml=[f'cluster_id：{label}','クラスター概要：未提供',f'入力範囲：{label}に所属する全{count}記事。重心に近い順に表示する。','<articles>']
            for a in articles:
                xml.extend([f'<article id="{a["article_id"]}" centroid_rank="{a["centroid_rank"]}">',f'<title>{escape(a["title"])}</title>',f'<url>{escape(a["url"])}</url>',f'<published_at>{escape(a["published_at"])}</published_at>','<body>'])
                xml.extend(f'[{p["paragraph_id"]}] {escape(p["text"])}' for p in a['paragraphs'])
                xml.extend(['</body>','</article>'])
            xml.append('</articles>')
            text='\n'.join(xml)
            payload={'model':'gpt-4.1-2025-04-14','instructions':prompt,'input':text,'temperature':0,'store':False,'max_output_tokens':16000}
            save(folder/'selection-request.json',payload)
            save(delivery/'input-articles.json',articles)
            (delivery/'selection-prompt.txt').write_text(prompt,encoding='utf-8')
            (delivery/'input-articles.xml').write_text(text,encoding='utf-8')
            meta={'cluster_id':label,'article_count':count,'body_chars':sum(a['body_chars'] for a in articles),'combinations_requested':combinations,'verified_source_hashes':count,'input_sha256':hashlib.sha256(text.encode()).hexdigest(),'instructions_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'previous_model_outputs_in_selection_input':False,'model':payload['model'],'temperature':0}
            save(delivery/'provenance.json',meta)
            inventory.append(meta)
    save(OUT/'inventory.json',inventory)
    print(json.dumps({'prepared':True,'clusters':[{k:v for k,v in a.items() if k in ('cluster_id','article_count','body_chars','combinations_requested')} for a in inventory],'total_articles':sum(a['article_count'] for a in inventory)},ensure_ascii=False),flush=True)

def unpack(response):
    assert response['status']=='completed',response.get('status')
    text=''.join(c['text'] for o in response.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text')
    assert text
    return text

def call_one(label,key):
    folder=WORK/label;delivery=OUT/label
    payload=read(folder/'selection-request.json')
    if (folder/'selection-response.json').exists():
        response=read(folder/'selection-response.json')
        unpack(response)
        return {'cluster_id':label,'status':'already_completed','model':response['model']}
    assert not (folder/'selection-intent.json').exists(),f'{label}: request already attempted; do not repeat'
    data=json.dumps(payload,ensure_ascii=False).encode()
    request=urllib.request.Request('https://api.openai.com/v1/responses',data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
    save(folder/'selection-intent.json',{'started_at':datetime.now(timezone.utc).isoformat(),'model':payload['model'],'request_sha256':hashlib.sha256(data).hexdigest()})
    start=time.monotonic()
    with LOCK:print(label+' API request started',flush=True)
    try:
        with urllib.request.urlopen(request,timeout=420) as response:
            result=json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        error=json.loads(e.read().decode())
        failure={'cluster_id':label,'status':'failed','kind':'HTTPError','http_status':e.code,'error_code':error.get('error',{}).get('code')}
        save(folder/'selection-error.json',failure)
        with LOCK:print(json.dumps(failure),flush=True)
        return failure
    except Exception as e:
        failure={'cluster_id':label,'status':'failed','kind':type(e).__name__,'reason_type':type(getattr(e,'reason',None)).__name__}
        save(folder/'selection-error.json',failure)
        with LOCK:print(json.dumps(failure),flush=True)
        return failure
    save(folder/'selection-response.json',result)
    answer=unpack(result)
    (delivery/'selection-result.md').write_text(answer+'\n',encoding='utf-8')
    execution={'cluster_id':label,'elapsed_seconds':time.monotonic()-start,'response_id':result['id'],'model':result['model'],'status':result['status'],'usage':result.get('usage')}
    save(delivery/'selection-execution.json',execution)
    match=re.search(r'selection_status\s*[：:]\s*\**(TWO_SETS|ONE_SET|NO_SET)',answer)
    compact={'cluster_id':label,'status':'completed','model_selection_status':match.group(1) if match else 'inspect_raw_output','output_chars':len(answer),'usage':result.get('usage')}
    with LOCK:print(json.dumps(compact,ensure_ascii=False),flush=True)
    return compact

def call_all():
    key=api_key()
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        pending={pool.submit(call_one,label,key):label for label in CLUSTERS}
        for future in concurrent.futures.as_completed(pending):
            label=pending[future]
            try:results.append(future.result())
            except Exception as e:
                failure={'cluster_id':label,'status':'local_failure','kind':type(e).__name__}
                results.append(failure)
                with LOCK:print(json.dumps(failure),flush=True)
    results.sort(key=lambda x:x['cluster_id'])
    save(OUT/'execution-summary.json',results)
    print(json.dumps({'finished':True,'completed':sum(x['status'] in ('completed','already_completed') for x in results),'clusters':len(results)},ensure_ascii=False),flush=True)

if __name__=='__main__':
    {'prepare':prepare,'call':call_all}[sys.argv[1]]()
