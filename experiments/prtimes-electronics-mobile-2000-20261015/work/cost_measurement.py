"""Reconcile API usage with the standard USD prices checked on 2026-10-15."""
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

PRICEBOOK={
 'gpt-6.1-sol':{'input':'2','cached':'0.10','write':'2.50','output':'10','long_context':True,'source':'https://developers.openai.com/api/docs/models/gpt-6.1-sol'},
 'gpt-6-astra':{'input':'10','cached':'1','write':'12.50','output':'50','long_context':True,'source':'https://developers.openai.com/api/docs/models/gpt-6-astra'},
 'gpt-4.1-2025-04-14':{'input':'2','cached':'0.50','write':None,'output':'8','long_context':False,'source':'https://developers.openai.com/api/docs/models/gpt-4.1'},
 'text-embedding-3-small':{'input':'0.02','cached':'0','write':None,'output':'0','long_context':False,'source':'https://developers.openai.com/api/docs/models/text-embedding-3-small'},
}

def measure(model,usage,tier='default'):
    if not usage:return {'cost_usd':None,'unpriced_reason':'API_USAGE_UNAVAILABLE'}
    price=PRICEBOOK[model];details=usage.get('input_tokens_details') or {}
    inputs=usage.get('input_tokens',usage.get('prompt_tokens',0))
    cached=details.get('cached_tokens',0);writes=details.get('cache_write_tokens',0)
    outputs=usage.get('output_tokens',0);reasoning=(usage.get('output_tokens_details') or {}).get('reasoning_tokens',0)
    uncached=inputs-cached-writes
    if uncached<0:raise ValueError('CACHE_TOKEN_COUNT_MISMATCH')
    info={'input_tokens':inputs,'uncached_input_tokens':uncached,'cached_input_tokens':cached,
          'cache_write_tokens':writes,'output_tokens':outputs,'reasoning_tokens_included_in_output':reasoning}
    if tier not in (None,'default','auto'):
        return {**info,'cost_usd':None,'unpriced_reason':'NON_STANDARD_SERVICE_TIER:'+str(tier)}
    if writes and price['write'] is None:
        return {**info,'cost_usd':None,'unpriced_reason':'CACHE_WRITE_PRICE_UNCONFIRMED'}
    long=price['long_context'] and inputs>272000
    in_factor=Decimal('2') if long else Decimal('1');out_factor=Decimal('1.5') if long else Decimal('1')
    cost=(Decimal(uncached)*Decimal(price['input'])+Decimal(cached)*Decimal(price['cached'])+Decimal(writes)*Decimal(price['write'] or '0'))*in_factor
    cost+=Decimal(outputs)*Decimal(price['output'])*out_factor
    return {**info,'long_context_surcharge':long,'cost_usd':str(cost/Decimal(1000000))}

def ledger(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

def write_reports(out,previous_ledger):
    rows=[]
    for phase,path in [('selection',previous_ledger),('generation_verification',out/'api-calls.jsonl')]:
        for row in ledger(path):
            model=row.get('model_returned') or row['model_requested']
            operation=row.get('operation') or ('embedding' if row.get('endpoint')=='embeddings' else 'selection')
            cost=measure(model,row.get('usage'),row.get('service_tier','default'))
            rows.append({'phase':phase,'operation':operation,'model':model,'response_id':row.get('response_id'),
                         'cluster_id':row.get('cluster_id'),'call_id':row.get('call_id'),**cost})
    grouped=defaultdict(list);operations=defaultdict(list)
    for row in rows:
        grouped[(row['phase'],row['model'])].append(row);operations[(row['phase'],row['model'],row['operation'])].append(row)
    for model in ['gpt-6.1-sol','gpt-6-astra']:
        grouped.setdefault(('generation_verification',model),[])
    def summarize(key,values):
        result={'phase':key[0],'model':key[1],'calls':len(values),
                'cost_usd':str(sum((Decimal(r['cost_usd']) for r in values if r['cost_usd'] is not None),Decimal('0'))),
                'unpriced_calls':sum(r['cost_usd'] is None for r in values)}
        for field in ['input_tokens','uncached_input_tokens','cached_input_tokens','cache_write_tokens','output_tokens','reasoning_tokens_included_in_output']:
            result[field]=sum(r.get(field,0) for r in values)
        if len(key)>2:result['operation']=key[2]
        return result
    totals=[summarize(k,v) for k,v in grouped.items()]
    result={'currency':'USD','price_checked_on':'2026-10-15','basis':'API response usage multiplied by published Standard rates; not a billing invoice',
            'pricebook_usd_per_million_tokens':PRICEBOOK,'by_model':totals,
            'by_operation':[summarize(k,v) for k,v in operations.items()],
            'generation_verification_cost_usd':str(sum((Decimal(r['cost_usd']) for r in totals if r['phase']=='generation_verification'),Decimal('0'))),
            'all_phases_cost_usd':str(sum((Decimal(r['cost_usd']) for r in totals),Decimal('0'))),
            'unpriced_calls':sum(r['cost_usd'] is None for r in rows),'calls':rows}
    (out/'costs.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'pricing.json').write_text(json.dumps(PRICEBOOK,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# モデル別コスト','',
      'APIが返した使用量に、2026年10月15日に確認した公開Standard単価を適用したUSD換算額。請求書上の確定額とは区別する。','',
      '| 工程 | モデル | 呼出数 | 入力 | キャッシュ読込 | キャッシュ書込 | 出力 | 推論（出力内数） | 費用 USD |',
      '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in totals:
        lines.append(f'| {row["phase"]} | {row["model"]} | {row["calls"]} | {row["input_tokens"]} | {row["cached_input_tokens"]} | {row["cache_write_tokens"]} | {row["output_tokens"]} | {row["reasoning_tokens_included_in_output"]} | {Decimal(row["cost_usd"]):.6f} |')
    lines+=['',f'今回の生成・検証: **${Decimal(result["generation_verification_cost_usd"]):.6f}**。',
            f'前段の埋め込み・選定を含む合計: **${Decimal(result["all_phases_cost_usd"]):.6f}**。','',
            'キャッシュ済み・書込トークンを通常入力から差し引いて各単価を適用する。推論トークンは出力トークンに含まれるため二重加算しない。Sol/Astraで入力が272,000トークンを超えた呼び出しには公式の長文追加料金を適用する。','',
            '失敗・不正応答でも使用量が返った呼び出しを含める。使用量を確認できない呼び出しは費用未確定として残し、0ドルとはみなさない。税・為替・個別契約割引は含めない。',
            f'費用未確定の呼出数: {result["unpriced_calls"]}。','',
            '初回生成・検証・修正・再検証別と各呼び出しの計算結果は`costs.json`、原使用量は`api-calls.jsonl`を参照。','',
            '公式単価: '+', '.join(f'[{model}]({p["source"]})' for model,p in PRICEBOOK.items())]
    (out/'costs.md').write_text('\n'.join(lines),encoding='utf-8')
    return result
