"""Verify real requests, immutable sources, persisted outputs, and cost ledgers."""
import json,sqlite3,hashlib,zipfile,argparse
from pathlib import Path
from collections import Counter
from decimal import Decimal
from run_generation import ROOT,OUT,SOURCE,hash_file
from cost_measurement import measure,write_reports,ledger

def value(response):
    return json.loads(''.join(c['text'] for o in response['output'] for c in o.get('content',[]) if c.get('type')=='output_text'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--allow-partial',action='store_true');args=parser.parse_args()
    manifest=json.loads((OUT/'run-manifest.json').read_text(encoding='utf-8'))
    db=sqlite3.connect(manifest['database']);db.row_factory=sqlite3.Row
    run=db.execute('select * from runs where id=?',(manifest['run_id'],)).fetchone()
    complete=run['step']=='complete' and run['error'] is None
    assert complete or args.allow_partial
    settings=json.loads(run['settings']);counts=Counter();repairs=Counter();errors=[]
    calls=ledger(OUT/'api-calls.jsonl')
    for call in calls:
        request=json.loads((OUT/call['request_file']).read_text(encoding='utf-8'))
        if call.get('error_type'):
            assert call.get('usage') is None
            assert not (OUT/call['response_file']).exists()
            errors.append({'call_id':call['call_id'],'error_code':call['error_code']})
            continue
        response=json.loads((OUT/call['response_file']).read_text(encoding='utf-8'))
        assert response['id']==call['response_id'] and response['usage']==call['usage']
        assert response['status']=='completed' and response['model']==request['model']==call['model_requested']==call['model_returned']
        assert call['request_sha256']==hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        assert request['reasoning']=={'effort':'medium'} and request['service_tier']=='default'
        assert request['store'] is False and not request.get('tools') and not request.get('previous_response_id')
        data=json.loads(request['input']);comparison=db.execute('select * from comparisons where id=?',(call['comparison_id'],)).fetchone()
        assert comparison['run_id']==manifest['run_id']
        fields=['source1','source2','source3'] if call['set_role']=='PRIMARY' else ['reserve1','reserve2','reserve3']
        expected=[]
        for field in fields:
            a=db.execute('select * from articles where id=?',(comparison[field],)).fetchone()
            expected.append({'title':a['title'],'url':a['url'],'published_at':a['published_at'],'text':a['body']})
        assert data['sources']==expected
        draft=db.execute('select * from drafts where comparison_id=? and set_role=? and revision=?',
                         (comparison['id'],call['set_role'],call['revision'])).fetchone()
        assert draft is not None
        output=value(response);operation=call['operation']
        if operation in ['generation','repair']:
            assert request['model']=='gpt-6.1-sol' and request['instructions']==settings['prompts']['generation']
            assert output['status']==draft['generation_status'] and output['reason']==draft['generation_reason']
            assert output['article_markdown']==draft['markdown']
            if operation=='repair':
                repairs[comparison['id']]+=1
                previous=db.execute('select d.markdown,v.reason from drafts d join verifications v on v.draft_id=d.id where d.comparison_id=? and d.set_role=? and d.revision=0',
                                    (comparison['id'],call['set_role'])).fetchone()
                assert data['article_markdown']==previous['markdown'] and data['feedback']==previous['reason']
        else:
            assert request['model']=='gpt-6-astra' and request['instructions']==settings['prompts']['verification']
            assert set(data)=={'article_markdown','sources','generation_instructions'}
            assert data['generation_instructions']==settings['prompts']['generation']
            assert data['article_markdown']==draft['markdown'] and draft['generation_status']=='APPROPRIATE'
            verification=db.execute('select * from verifications where draft_id=?',(draft['id'],)).fetchone()
            assert output=={'status':verification['status'],'score':verification['score'],'reason':verification['reason']}
        assert call['cost']==measure(request['model'],response['usage'],response.get('service_tier','default'))
        counts[operation]+=1
    assert all(n==1 for n in repairs.values())
    selected=db.execute('select count(*) from comparisons where run_id=? and source1 is not null',(run['id'],)).fetchone()[0]
    assert counts['generation']>=selected if complete else counts['generation']<=selected
    unverified=0
    for row in db.execute('select d.*,v.score from drafts d join comparisons c on c.id=d.comparison_id left join verifications v on v.draft_id=d.id where c.run_id=?',(run['id'],)):
        if row['generation_status']=='APPROPRIATE':
            if row['score'] is None:unverified+=1
            if complete:assert row['score'] is not None
        else:assert row['score'] is None and not row['markdown']
    assert hash_file(SOURCE)==manifest['parent_selection_database_sha256']
    assert db.execute('pragma integrity_check').fetchone()[0]=='ok' and not db.execute('pragma foreign_key_check').fetchall()
    costs=write_reports(OUT,ROOT/'outputs/api-calls.jsonl')
    assert Decimal(costs['generation_verification_cost_usd'])==sum((Decimal(c['cost']['cost_usd']) for c in calls if c.get('cost',{}).get('cost_usd') is not None),Decimal('0'))
    check={'state':'complete' if complete else 'partial','run_id':run['id'],'api_requests_reconciled':len(calls),'api_calls_by_operation':dict(counts),
           'sources_and_full_texts_match':True,'frozen_generation_instructions_match':True,
           'independent_verification_inputs_match':True if counts['verification']+counts['reverification'] else None,
           'verification_api_calls':counts['verification']+counts['reverification'],'actual_returned_models_match':True,
           'all_generated_articles_verified':unverified==0,'unverified_generated_drafts':unverified,
           'failed_requests':errors,'max_repairs_per_comparison':max(repairs.values(),default=0),
           'generation_verification_cost_usd':costs['generation_verification_cost_usd'],
           'cost_unpriced_calls':costs['unpriced_calls'],'source_selection_database_unchanged':True,'integrity':'ok','foreign_keys':'ok'}
    (OUT/'reconciliation.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf-8')
    root=ROOT/'work/runtime'
    with zipfile.ZipFile(OUT/'execution-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in root.rglob('*'):
            if p.is_file() and not any(x in p.parts for x in ['__pycache__','.pytest_cache','.ruff_cache']):archive.write(p,'runtime/'+p.relative_to(root).as_posix())
        for name in ['run_generation.py','cost_measurement.py','reconcile_generation.py','check_generation_models.py']:
            archive.write(ROOT/'work'/name,name)
    with zipfile.ZipFile(OUT/'execution-source.zip') as archive:
        assert not any(Path(n).name=='.env' for n in archive.namelist())
        hashes={n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()}
    (OUT/'source-hashes.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    db.close();print(json.dumps(check,ensure_ascii=False))

if __name__=='__main__':main()
