import hashlib
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / 'outputs/promising-comparison-articles-20261015'
OUT.mkdir(parents=True, exist_ok=True)
groups = [
    ('C03', 'RESERVE', ['F865', 'F456', 'F932']),
    ('C10', 'PRIMARY', ['F950', 'F677', 'F698']),
    ('C13', 'PRIMARY', ['F438', 'F065', 'F637']),
    ('C17', 'PRIMARY', ['F488', 'F333', 'F411']),
    ('C22', 'PRIMARY', ['F730', 'F903', 'F831']),
    ('C22', 'RESERVE', ['F730', 'F903', 'F673']),
    ('C27', 'RESERVE', ['F902', 'F711', 'F278']),
]
manifest = []
for cluster, role, ids in groups:
    base = 'C03-C10-allarticles-selection-20261015' if cluster in ['C03', 'C10'] else 'C11-C30-allarticles-selection-20261015'
    original = ROOT / 'outputs' / base / cluster / 'input-articles.json'
    records = json.loads(original.read_text(encoding='utf-8-sig'))
    selected = [next(a for a in records if a['article_id'] == aid) for aid in ids]
    name = f'{cluster}-{role.lower()}'
    for a in selected:
        digest = hashlib.sha256((a['title']+'\n\n'+a['body']).encode('utf-8')).hexdigest()
        assert digest == a['input_hash'], (cluster, a['article_id'])
    (OUT / f'{name}-sources.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest.append({'group': name, 'cluster': cluster, 'role': role, 'article_ids': ids,
        'input_file': str(original), 'sources_file': f'{name}-sources.json',
        'sources': [{k:a[k] for k in ['article_id','title','url','published_at','input_hash','body_chars']} for a in selected]})
(OUT / 'manifest.json').write_text(json.dumps({'date':'2026-10-15','author':'このチャットのアシスタント自身',
    'generation_method':'本文を読んだうえで本チャット内で執筆。外部モデルAPI・別エージェントによる生成なし。',
    'source_policy':'保存済みの各組3記事の本文のみ。外部検索・リンク先の追加取得なし。',
    'groups':manifest}, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'generation-prompt.txt').write_text((ROOT/'work/c01-generation-prompt.txt').read_text(encoding='utf-8-sig'), encoding='utf-8')
print(f'Prepared {len(manifest)} groups. All source hashes match.')
