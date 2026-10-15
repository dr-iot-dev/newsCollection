"""Package unedited model outputs; record execution separately from editorial review."""
import hashlib
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE/'outputs/promising-comparison-gpt61-sol-20261015'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

inventory = read(OUT/'inventory.json')
prompt = (OUT/'generation-prompt.txt').read_text(encoding='utf-8')
original_prompt = (BASE/'outputs/promising-comparison-articles-20261015/generation-prompt.txt').read_text(encoding='utf-8')
assert prompt == original_prompt
rows=[]
sections=[]
for item in inventory:
    name=item['group']; folder=OUT/name
    execution=read(folder/'generation-execution.json')
    raw=read(folder/'generation-response.json')
    request=read(folder/'generation-request.json')
    articles=read(folder/'input-articles.json')
    response_text='\n'.join(c['text'] for o in raw.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text')
    output=(folder/'generation-result.md').read_text(encoding='utf-8')
    assert output==response_text+'\n'
    assert execution['model_returned'].startswith('gpt-6.1-sol')
    assert execution['response_status']=='completed'
    assert response_text and not execution['refusals']
    assert request['instructions']==prompt
    assert request.get('tools') is None and request.get('previous_response_id') is None
    assert len(articles)==3
    for a in articles:
        assert hashlib.sha256((a['title']+'\n\n'+a['body']).encode()).hexdigest()==a['input_hash']
    verdict=execution['model_verdict']
    assert verdict in ('APPROPRIATE','INAPPROPRIATE'),name
    source_map={x['article_id']:x for x in articles}
    unknown_ids=sorted(set(re.findall(r'\bF\d{3}\b',response_text))-set(source_map))
    raw_urls=set(re.findall(r'https?://[^\s)\]<>「」]+',response_text))
    known_urls={x['url'] for x in articles}
    extra_urls=sorted(raw_urls-known_urls)
    # IDs and URL consistency are checkable mechanically; their semantic support
    # and gate decisions require the separate editorial review.
    row={**{k:execution[k] for k in ['group','model_requested','model_returned','response_id','response_status','model_verdict','output_chars','usage','elapsed_seconds']},
        'cluster_id':item['cluster_id'],'role':item['role'],'article_ids':item['article_ids'],
        'result_file':f'{name}/generation-result.md','unknown_article_ids':unknown_ids,
        'urls_not_equal_to_input_article_urls':extra_urls,
        'raw_output_unchanged':True,'source_hashes_verified':3}
    rows.append(row)
    source_links=' ／ '.join(f'[{x["article_id"]}：元記事]({x["url"]})' for x in articles)
    sections.append(f'## {item["cluster_id"]}・{item["role"]}\n\n生成モデル：{execution["model_returned"]}  \n入力記事：{"・".join(item["article_ids"])}  \n出典リンク（入力記録から付記）：{source_links}\n\n以下はモデルの返答原文。本文・判定の編集はしていない。\n\n'+output)
count_a=sum(x['model_verdict']=='APPROPRIATE' for x in rows)
count_i=sum(x['model_verdict']=='INAPPROPRIATE' for x in rows)
usage={key:sum(x['usage'].get(key,0) for x in rows) for key in ['input_tokens','output_tokens','total_tokens']}
usage['reasoning_tokens']=sum(x['usage'].get('output_tokens_details',{}).get('reasoning_tokens',0) for x in rows)
summary={'date':'2026-10-15','model':'gpt-6.1-sol','reasoning_effort':'medium',
    'response_count':len(rows),'model_appropriate':count_a,'model_inappropriate':count_i,
    'usage':usage,'generation_prompt_identical_to_previous_run':True,
    'previous_verdicts_or_generated_articles_in_model_input':False,
    'tools_enabled':False,'store':False,'max_output_tokens_per_request':24000,
    'reselection':False,'results':rows}
save(OUT/'summary.json',summary)
references=[]
for row in rows:
    folder=OUT/row['group']
    sources={a['article_id']:a for a in read(folder/'input-articles.json')}
    text=(folder/'generation-result.md').read_text(encoding='utf-8')
    if row['model_verdict']=='INAPPROPRIATE':
        assert not re.search(r'^#{1,6}\s',text,re.M),row['group']
        assert '不合格条件' in text and '比較成立に必要な情報' in text
    for block in re.findall(r'\[([^\]\n]+)\]|〔([^〕\n]+)〕',text):
        citation=block[0] or block[1]
        if not re.search(r'F\d{3}',citation): continue
        for part in re.finditer(r'(F\d{3})(.*?)(?=F\d{3}|$)',citation):
            aid,body=part.groups()
            assert aid in sources,(row['group'],aid)
            known={p['paragraph_id'] for p in sources[aid]['paragraphs']}
            for paragraph in re.findall(r'P\d{3}',body):
                assert paragraph in known,(row['group'],aid,paragraph)
                references.append({'group':row['group'],'article_id':aid,'paragraph_id':paragraph})
save(OUT/'verification.json',{'completed_responses':7,'requested_model_verified':True,
    'prompt_identical_to_previous':True,'all_source_hashes_match':True,
    'raw_outputs_unchanged':True,'inappropriate_outputs_have_no_article_body':True,
    'explicit_citation_paragraph_endpoints_checked':len(references),
    'references':references,
    'limitation':'機械確認は参照の実在・入出力整合性に限る。比較の意味と根拠は本チャットで別途確認。独立評価モデルによる採点ではない。'})
intro=f'# GPT 6.1 Solによる比較記事生成・返答全文\n\n2026年10月15日。前回と同じ7組、同じ生成指示を使用。モデル自身の判定はAPPROPRIATEが{count_a}組、INAPPROPRIATEが{count_i}組。各返答は未編集で収録する。モデルの合格判定と、本文根拠を含めた編集上の採否は区別する。\n\n[結果一覧・実行条件・確認所見](report.md)\n\n'
(OUT/'results-all.md').write_text(intro+'\n\n---\n\n'.join(sections),encoding='utf-8')
print(json.dumps({'responses':len(rows),'appropriate':count_a,'inappropriate':count_i,'usage':usage,
    'results':[{k:x[k] for k in ['group','model_returned','model_verdict','output_chars','unknown_article_ids','urls_not_equal_to_input_article_urls']} for x in rows]},ensure_ascii=False,indent=2))
