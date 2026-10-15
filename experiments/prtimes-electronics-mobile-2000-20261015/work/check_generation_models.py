import json
from run_selection import provider,OUT

client=provider()
records=[]
for model in ['gpt-6.1-sol','gpt-6.1-astra','gpt-6-astra']:
    response=client.client.get('models/'+model)
    value=response.json()
    record={'requested_model':model,'http_status':response.status_code,
            'returned_model':value.get('id'),'error_code':value.get('error',{}).get('code')}
    records.append(record)
    print(json.dumps(record),flush=True)
response=client.client.get('models')
if response.status_code==200:
    ids=[row['id'] for row in response.json().get('data',[]) if 'astra' in row.get('id','').lower()]
    print('accessible_astra_models',json.dumps(ids),flush=True)
(OUT/'generation-model-access.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
client.close()
