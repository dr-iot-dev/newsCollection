"""Package generated originals and article mappings without modifying image pixels."""
import hashlib
import html
import json
import struct
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/wordpress-featured-images'
ARTICLES = ROOT / 'outputs/generation-sol-astra-20261015/articles'

manifest = json.loads((OUT / 'generation-manifest.json').read_text(encoding='utf-8'))
results = json.loads((ARTICLES / 'results.json').read_text(encoding='utf-8'))
eligible = {a['cluster_id'] for a in results['articles'] if a['status'] == 'eligible'}
assert eligible == {j['cluster'] for j in manifest['jobs']}
lines = ['# WordPress用アイキャッチ画像', '',
         '採用可の比較記事6本に対応する、文字・ロゴなしの横長イラスト。画像は生成されたPNG原本で、画素の変更やリサイズは行っていない。実製品の正確な外観・性能を示す画像ではなく、記事テーマを表す概念イラストである。', '',
         '[一覧プレビュー](gallery.html)・[6枚をまとめてダウンロード](../wordpress-featured-images.zip)', '',
         '|記事|PNG|サイズ|代替テキスト案|', '|---|---|---|---|']
cards = []
for job in manifest['jobs']:
    path = OUT / job['file']
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    width, height = struct.unpack('>II', data[16:24])
    assert width > height and width >= 1200
    assert data == Path(job['source_path']).read_bytes()
    article_file = f"cluster-{job['cluster']}.md"
    title = (ARTICLES / article_file).read_text(encoding='utf-8').splitlines()[0].removeprefix('# ')
    job.update(title=title, article=f'../generation-sol-astra-20261015/articles/{article_file}',
               width=width, height=height, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    lines.append(f"|[{title}]({job['article']})|[{job['label']}]({job['file']})|{width}×{height}|{job['alt']}|")
    cards.append(f'<article><a href="{html.escape(job["file"])}" download><img src="{html.escape(job["file"])}" alt="{html.escape(job["alt"])}"></a><h2>{html.escape(title)}</h2><p>{width}×{height} · PNG · {len(data)/1024/1024:.2f} MB</p><p><a href="{html.escape(job["file"])}" download>画像を保存</a> · <a href="{html.escape(job["article"])}">記事</a></p><p class="alt">代替テキスト案：{html.escape(job["alt"])}</p></article>')
lines += ['', '内蔵の `image_gen` で生成。最終プロンプト全文と記事対応、生成元、寸法、SHA-256は[generation-manifest.json](generation-manifest.json)に保存した。スマホケースの最初の写真風案は採用せず、最終6枚のみを収録した。', '',
          '画像生成ツールから課金対象の使用量・モデル名・費用は返らなかったため、画像生成費用は未計測（0ドルを意味しない）。記事生成・検証のAPI費用とは別である。', '']
(OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
page = '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WordPress用アイキャッチ画像6枚</title><style>body{font:16px/1.7 system-ui,sans-serif;background:#f4f4ef;color:#26323a;margin:0;padding:32px}main{max-width:1300px;margin:auto}h1{font-size:28px}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:24px}article{background:white;border-radius:14px;padding:18px;box-shadow:0 2px 12px #00000008}img{width:100%;height:auto;border-radius:8px}h2{font-size:18px;margin:14px 0 8px}a{color:#236779}p{margin:8px 0}.alt{font-size:14px;color:#56636b}</style><main><h1>WordPress用アイキャッチ画像6枚</h1><p>採用可の記事に対応する横長イラスト。画像をクリックするとPNGを保存できます。</p><p><a href="../wordpress-featured-images.zip" download>6枚と対応表をまとめてダウンロード（ZIP）</a></p><section>' + ''.join(cards) + '</section></main></html>'
(OUT / 'gallery.html').write_text(page, encoding='utf-8')
(OUT / 'generation-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
archive_path = ROOT / 'outputs/wordpress-featured-images.zip'
with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(OUT.iterdir()):
        if p.is_file():
            archive.write(p, 'wordpress-featured-images/' + p.name)
with zipfile.ZipFile(archive_path) as archive:
    assert archive.testzip() is None
    assert sum(n.endswith('.png') for n in archive.namelist()) == 6
report = ROOT / 'outputs/generation-sol-astra-20261015/report.md'
text = report.read_text(encoding='utf-8')
link = '[採用可6記事のWordPress用アイキャッチ画像](../wordpress-featured-images/README.md)'
if link not in text:
    report.write_text(text + '\n\n' + link + '。\n', encoding='utf-8')
print(json.dumps({'images':len(manifest['jobs']), 'pngs_unchanged':True, 'zip_integrity':'ok', 'zip_bytes':archive_path.stat().st_size,
                  'dimensions':{j['cluster']:[j['width'],j['height']] for j in manifest['jobs']}}))
