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
WORK=BASE/'work/c01-all13-trial'
OUT=BASE/'outputs/C01-all13-selection-20261015'
ROOT=Path(r'\\TRUENAS\dev\codex\newsWeave')
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

def save(name,value):
    (WORK/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def prepare():
    records=json.loads((ROOT/'.local/seven-stage-real-c01-20261015/cluster-input.json').read_text(encoding='utf-8-sig'))
    ranks=json.loads((BASE/'work/c01-trial/ranking-all13.json').read_text(encoding='utf-8'))
    assert len(records)==len(ranks)==13
    by_id={r['article']['id']:r for r in records}
    assert set(by_id)=={r['article_id'] for r in ranks}
    inputs=[]
    for rank in ranks:
        r=by_id[rank['article_id']]
        a=r['article']
        assert hashlib.sha256((a['title']+'\n\n'+a['body']).encode()).hexdigest()==r['input_hash']
        assert len(a['body'])==rank['body_chars']
        paragraphs=[{'paragraph_id':f'P{i:03d}','text':p} for i,p in enumerate(a['body'].split('\n\n'),1)]
        inputs.append({**rank,'body':a['body'],'paragraphs':paragraphs})
    old_prompt=(BASE/'work/c01-selection-prompt.txt').read_text(encoding='utf-8')
    prompt=old_prompt.replace('7記事','13記事').replace('全35通り','全286通り')
    assert prompt!=old_prompt and math.comb(len(inputs),3)==286
    (WORK/'selection-prompt.txt').write_text(prompt,encoding='utf-8')
    xml=['cluster_id：C01','クラスター概要：未提供','入力範囲：C01に所属する全13記事。重心に近い順に表示する。','<articles>']
    for a in inputs:
        xml.extend([f'<article id="{a["article_id"]}" centroid_rank="{a["centroid_rank"]}">',f'<title>{escape(a["title"])}</title>',f'<url>{escape(a["url"])}</url>',f'<published_at>{escape(a["published_at"])}</published_at>','<body>'])
        xml.extend(f'[{p["paragraph_id"]}] {escape(p["text"])}' for p in a['paragraphs'])
        xml.extend(['</body>','</article>'])
    xml.append('</articles>')
    text='\n'.join(xml)
    (WORK/'input-all13.xml').write_text(text,encoding='utf-8')
    save('input-all13.json',inputs)
    save('selection-request.json',{'model':'gpt-4.1-2025-04-14','instructions':prompt,'input':text,'temperature':0,'store':False,'max_output_tokens':16000})
    save('provenance.json',{'cluster_id':'C01','requested_label':'C0 interpreted as preceding C01','articles':13,'combination_count':286,'input_body_chars':sum(a['body_chars'] for a in inputs),'model':'gpt-4.1-2025-04-14','temperature':0,'prompt_changes_from_seven_article_trial':['7記事 -> 13記事','全35通り -> 全286通り'],'previous_model_outputs_in_selector_input':False,'input_sha256':hashlib.sha256(text.encode()).hexdigest(),'instructions_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'created_at':datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'prepared':True,'articles':len(inputs),'body_chars':sum(a['body_chars'] for a in inputs),'candidate_combinations':286},ensure_ascii=False))

def call():
    assert not (WORK/'selection-intent.json').exists(),'Do not duplicate a potentially sent request'
    payload=json.loads((WORK/'selection-request.json').read_text(encoding='utf-8'))
    data=json.dumps(payload,ensure_ascii=False).encode()
    request=urllib.request.Request('https://api.openai.com/v1/responses',data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+api_key()},method='POST')
    save('selection-intent.json',{'started_at':datetime.now(timezone.utc).isoformat(),'model':payload['model'],'request_sha256':hashlib.sha256(data).hexdigest()})
    start=time.monotonic()
    print('GPT-4.1 all-13-article selection request started',flush=True)
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
    for name in ['selection-result.md','selection-execution.json','selection-prompt.txt','input-all13.json','input-all13.xml','provenance.json']:
        (OUT/name).write_bytes((WORK/name).read_bytes())
    print(json.dumps({'completed':True,'model':result['model'],'usage':result.get('usage'),'output_chars':len(answer)},ensure_ascii=False),flush=True)

if __name__=='__main__':
    {'prepare':prepare,'call':call}[sys.argv[1]]()
