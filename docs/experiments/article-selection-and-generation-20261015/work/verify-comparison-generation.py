import json
import re
from pathlib import Path

out = Path('outputs/promising-comparison-articles-20261015')
m = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
a = json.loads((out/'assessment.json').read_text(encoding='utf-8'))
manifest = {x['group']:x for x in m['groups']}
sections = []
success = 0
fail = 0
checked_refs = 0
for r in a['results']:
    group = r['group']
    records = json.loads((out/manifest[group]['sources_file']).read_text(encoding='utf-8'))
    sources = {x['article_id']:x for x in records}
    paragraph_ids = {aid:{p['paragraph_id'] for p in x['paragraphs']} for aid,x in sources.items()}
    file = r.get('article_file',r.get('result_file'))
    content = (out/file).read_text(encoding='utf-8')
    assert r['status'] in content
    assert len(sources)==3
    if r['status']=='APPROPRIATE':
        success += 1
        assert '\n---\n' in content
        assert len(r['common_axes'])>=3
        assert len(r['differentiating_axes'])>=2
        for axis in r['common_axes']:
            assert set(axis['evidence'])==set(sources)
            for aid,refs in axis['evidence'].items():
                assert refs
                for ref in refs: assert ref in paragraph_ids[aid],(group,aid,ref)
        assert set(r['differentiating_axes']) <= {x['axis'] for x in r['common_axes']}
    else:
        fail += 1
        assert '\n---\n' not in content, f'Unexpected article body: {group}'
        assert '比較成立に必要な情報' in content
        for aid,refs in r['critical_evidence'].items():
            for ref in refs: assert ref in paragraph_ids[aid],(group,aid,ref)
    for aid in re.findall(r'F\d{3}',content): assert aid in sources,(group,aid)
    for aid,ref in re.findall(r'(F\d{3})・(P\d{3})',content):
        assert ref in paragraph_ids[aid],(group,aid,ref)
        checked_refs += 1
    for label,url in re.findall(r'\[([^\]]+)\]\((https://[^)]+)\)',content):
        if (match:=re.search(r'F\d{3}',label)):
            assert url == sources[match[0]]['url'], (group,label,url)
    sections.append(f'## {group}\n\n'+content)
assert success==3 and fail==4
intro = '# 比較記事生成結果・全文\n\n2026年10月15日。このチャットのアシスタント自身による執筆。7組中3組で記事を生成、4組は不適。各組の判定・制約・本文または不適理由を順に収録する。\n\n[結果一覧と実行条件](report.md)\n\n'
(out/'results-all.md').write_text(intro+'\n\n---\n\n'.join(sections),encoding='utf-8')
result={'groups':len(a['results']),'articles':success,'inappropriate':fail,'explicit_paragraph_references_checked':checked_refs,
    'checks':['各組3記事と出典の対応','判定と本文有無の一致','適切組の比較軸数・差異軸数・3記事分の根拠の有無','参照段落IDの実在','出典リンクと入力URLの一致'],
    'limitation':'形式と参照整合性の機械確認。意味内容・比較適切性は執筆担当自身による確認であり、独立評価ではない。'}
(out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
