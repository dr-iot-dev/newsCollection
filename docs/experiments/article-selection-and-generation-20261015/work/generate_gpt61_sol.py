"""Run the seven existing candidate triplets without exposing prior verdicts."""
import concurrent.futures
import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from c01_trial import api_key

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / 'outputs/promising-comparison-articles-20261015'
OUT = BASE / 'outputs/promising-comparison-gpt61-sol-20261015'
WORK = BASE / 'work/promising-comparison-gpt61-sol'
MODEL = 'gpt-6.1-sol'
LOCK = threading.Lock()

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def now():
    return datetime.now(timezone.utc).isoformat()

def prepare():
    OUT.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    prompt = (SOURCE/'generation-prompt.txt').read_text(encoding='utf-8-sig')
    assert prompt == (BASE/'work/c01-generation-prompt.txt').read_text(encoding='utf-8-sig')
    (OUT/'generation-prompt.txt').write_text(prompt, encoding='utf-8')
    # Read the manifest only for IDs and the original article snapshots; never read
    # the previous assistant's generated articles, assessments, or review report.
    groups = read(SOURCE/'manifest.json')['groups']
    inventory = []
    for group in groups:
        name = group['group']
        folder = OUT/name
        folder.mkdir(exist_ok=True)
        articles = read(SOURCE/group['sources_file'])
        assert [a['article_id'] for a in articles] == group['article_ids']
        assert len({a['article_id'] for a in articles}) == 3
        for a in articles:
            assert hashlib.sha256((a['title']+'\n\n'+a['body']).encode()).hexdigest() == a['input_hash']
            assert '\n\n'.join(p['text'] for p in a['paragraphs']) == a['body']
        xml = [f'クラスターID：{group["cluster"]}', f'使用組：{group["role"]}',
               '比較対象は以下の3記事から特定してください。', '<articles>']
        for a in articles:
            xml.extend([f'<article id="{a["article_id"]}">',
                f'<title>{escape(a["title"])}</title>', f'<url>{escape(a["url"])}</url>',
                f'<published_at>{escape(a["published_at"])}</published_at>', '<body>'])
            xml.extend(f'[{p["paragraph_id"]}] {escape(p["text"])}' for p in a['paragraphs'])
            xml.extend(['</body>', '</article>'])
        xml.append('</articles>')
        input_text = '\n'.join(xml)
        request = {'model': MODEL, 'instructions': prompt, 'input': input_text,
            'reasoning': {'effort':'medium'}, 'store':False, 'max_output_tokens':24000}
        save(folder/'input-articles.json', articles)
        (folder/'input-articles.xml').write_text(input_text, encoding='utf-8')
        save(folder/'generation-request.json', request)
        metadata = {'group':name,'cluster_id':group['cluster'],'role':group['role'],
            'article_ids':group['article_ids'],'model_requested':MODEL,
            'reasoning_effort':'medium','store':False,'max_output_tokens':24000,
            'source_hashes':{a['article_id']:a['input_hash'] for a in articles},
            'instructions_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
            'input_sha256':hashlib.sha256(input_text.encode()).hexdigest(),
            'input_body_chars':sum(len(a['body']) for a in articles),
            'prior_verdicts_or_articles_in_input':False,'tools_provided':False,
            'input_body_truncated':False}
        save(folder/'provenance.json',metadata)
        inventory.append(metadata)
    save(OUT/'inventory.json',inventory)
    print(json.dumps({'prepared':len(inventory),'model':MODEL,'source_hashes_verified':21,
        'body_chars':sum(x['input_body_chars'] for x in inventory)},ensure_ascii=False),flush=True)

def call_one(name, key):
    folder = OUT/name
    work = WORK/name
    work.mkdir(exist_ok=True)
    if (folder/'generation-response.json').exists():
        result = read(folder/'generation-response.json')
        return {'group':name,'status':'already_returned','response_status':result.get('status'),'model':result.get('model')}
    assert not (work/'intent.json').exists(), f'{name}: prior attempt requires inspection'
    payload = read(folder/'generation-request.json')
    data = json.dumps(payload,ensure_ascii=False).encode()
    request = urllib.request.Request('https://api.openai.com/v1/responses', data=data,
        headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
    save(work/'intent.json',{'started_at':now(),'model':MODEL,'request_sha256':hashlib.sha256(data).hexdigest()})
    start = time.monotonic()
    with LOCK: print(name+' started',flush=True)
    try:
        with urllib.request.urlopen(request,timeout=600) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        try: details = json.loads(error.read().decode()).get('error',{})
        except Exception: details = {}
        failure = {'group':name,'status':'request_failed','http_status':error.code,
            'error_type':details.get('type'),'error_code':details.get('code'),
            'parameter':details.get('param')}
        save(work/'error.json',failure)
        with LOCK: print(json.dumps(failure),flush=True)
        return failure
    except Exception as error:
        failure = {'group':name,'status':'transport_failed','error_type':type(error).__name__,
            'reason_type':type(getattr(error,'reason',None)).__name__}
        save(work/'error.json',failure)
        with LOCK: print(json.dumps(failure),flush=True)
        return failure
    save(folder/'generation-response.json',result)
    text = '\n'.join(c['text'] for o in result.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text')
    (folder/'generation-result.md').write_text(text+'\n',encoding='utf-8')
    refusals = [c.get('refusal','') for o in result.get('output',[]) for c in o.get('content',[]) if c.get('type')=='refusal']
    match = re.search(r'判定\s*[：:]\s*\**(INAPPROPRIATE|APPROPRIATE)',text)
    execution = {'group':name,'finished_at':now(),'elapsed_seconds':time.monotonic()-start,
        'response_id':result.get('id'),'model_requested':MODEL,'model_returned':result.get('model'),
        'response_status':result.get('status'),'usage':result.get('usage'),
        'incomplete_details':result.get('incomplete_details'),'refusals':refusals,
        'model_verdict':match[1] if match else None,'output_chars':len(text),
        'output_sha256':hashlib.sha256(text.encode()).hexdigest()}
    save(folder/'generation-execution.json',execution)
    compact = {k:execution[k] for k in ['group','model_returned','response_status','model_verdict','output_chars','elapsed_seconds']}
    with LOCK: print(json.dumps(compact,ensure_ascii=False),flush=True)
    return compact

def call(names):
    inventory = read(OUT/'inventory.json')
    valid = [x['group'] for x in inventory]
    if not names: names = valid
    assert all(x in valid for x in names)
    key = api_key()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(call_one,name,key):name for name in names}
        for future in concurrent.futures.as_completed(futures):
            try: results.append(future.result())
            except Exception as error:
                failure={'group':futures[future],'status':'local_error','error_type':type(error).__name__}
                results.append(failure)
                print(json.dumps(failure),flush=True)
    save(WORK/('execution-'+datetime.now().strftime('%H%M%S')+'.json'),results)
    print(json.dumps({'run_finished':True,'returned':len(results)},ensure_ascii=False),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='prepare': prepare()
    elif sys.argv[1]=='call': call(sys.argv[2:])
