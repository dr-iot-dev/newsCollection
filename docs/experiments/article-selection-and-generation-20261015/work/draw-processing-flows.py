import hashlib
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/processing-flow-20261015'
FONT='C:/Windows/Fonts/YuGothM.ttc'
COLORS={'blue':('#eff6ff','#2563eb'),'green':('#ecfdf5','#059669'),
        'red':('#fff1f2','#e11d48'),'amber':('#fffbeb','#d97706'),
        'gray':('#f1f5f9','#64748b'),'white':('#ffffff','#94a3b8')}

class Diagram:
    def __init__(self,w,h,title,subtitle):
        self.w=w; self.h=h
        self.im=Image.new('RGB',(w,h),'#f8fafc'); self.d=ImageDraw.Draw(self.im)
        self.svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">',
          f'<title>{escape(title)}</title><desc>{escape(subtitle)}</desc>',
          '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="context-stroke"/></marker></defs>',
          f'<rect width="{w}" height="{h}" fill="#f8fafc"/>']
        self.text(60,58,title,38,anchor='left')
        self.text(60,112,subtitle,21,color='#475569',anchor='left')

    def text(self,x,y,value,size=25,color='#0f172a',anchor='middle'):
        font=ImageFont.truetype(FONT,size)
        self.d.text((x,y),value,font=font,fill=color,anchor='lm' if anchor=='left' else 'mm')
        self.svg.append(f'<text x="{x}" y="{y}" text-anchor="{"start" if anchor=="left" else "middle"}" dominant-baseline="central" font-family="Yu Gothic,Meiryo,sans-serif" font-size="{size}" fill="{color}">{escape(value)}</text>')

    def box(self,x,y,w,h,lines,kind='blue',diamond=False,dashed=False):
        fill,stroke=COLORS[kind]
        if diamond:
            points=[(x+w/2,y),(x+w,y+h/2),(x+w/2,y+h),(x,y+h/2)]
            self.d.polygon(points,fill=fill,outline=stroke,width=3)
            p=' '.join(f'{a},{b}' for a,b in points)
            self.svg.append(f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>')
        else:
            self.d.rounded_rectangle((x,y,x+w,y+h),radius=18,fill=fill,outline=stroke,width=3)
            dash='stroke-dasharray="10 7"' if dashed else ''
            self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{fill}" stroke="{stroke}" stroke-width="3" {dash}/>')
        size=25
        limit=w-36 if not diamond else w*.64
        while size>17 and max(ImageFont.truetype(FONT,size).getlength(t) for t in lines)>limit:size-=1
        assert max(ImageFont.truetype(FONT,size).getlength(t) for t in lines)<=limit
        line_height=size+12
        assert line_height*(len(lines)-1)+size<h-12
        for i,line in enumerate(lines):
            self.text(x+w/2,y+h/2+(i-(len(lines)-1)/2)*line_height,line,size)

    def arrow(self,points,label=None,label_at=None,dashed=False,color='#475569'):
        if dashed:
            for a,b in zip(points,points[1:]):
                length=math.dist(a,b)
                for s in range(0,int(length),18):
                    t=min(s+10,length)
                    p=(a[0]+(b[0]-a[0])*s/length,a[1]+(b[1]-a[1])*s/length)
                    q=(a[0]+(b[0]-a[0])*t/length,a[1]+(b[1]-a[1])*t/length)
                    self.d.line((p,q),fill=color,width=3)
        else:self.d.line(points,fill=color,width=3,joint='curve')
        a,b=points[-2:]; angle=math.atan2(b[1]-a[1],b[0]-a[0])
        wings=[(b[0]-15*math.cos(angle-d),b[1]-15*math.sin(angle-d)) for d in (-.4,.4)]
        self.d.polygon([b,*wings],fill=color)
        data='M'+' L'.join(f'{x},{y}' for x,y in points)
        dash='stroke-dasharray="10 8"' if dashed else ''
        self.svg.append(f'<path d="{data}" fill="none" stroke="{color}" stroke-width="3" {dash} marker-end="url(#arrow)"/>')
        if label:
            x,y=label_at
            self.text(x,y,label,21,color)

    def save(self,name):
        self.svg.append('</svg>')
        (OUT/(name+'.svg')).write_text('\n'.join(self.svg),encoding='utf-8')
        self.im.save(OUT/(name+'.png'))

d=Diagram(1600,1840,'今回の実験：記事選定から比較記事生成まで',
          '実線＝実施済み　破線＝未実施の独立検証　｜　2026-10-15の保存記録に基づく')
nodes=[
 (150,90,['保存済みの元記事本文・埋め込み・クラスター所属']),
 (285,100,['C01〜C30：各クラスターの全所属記事を入力','実験入力327件／重心に近い順で提示']),
 (430,100,['GPT-4.1がG1〜G6で選定','本命・予備：最大2組／不足時は1組・0組']),
 (575,100,['本チャットが候補の本文根拠を照合','用途・比較単位・対象重複・根拠不足を確認']),
 (720,100,['有望候補などから生成対象の7組を固定','C03予備・C10・C13・C17・C22両組・C27予備']),
 (865,110,['GPT 6.1 Sol：各組を独立に実行','3原文＋同じ生成指示／過去の判定は入力しない'])]
for y,h,lines in nodes:d.box(430,y,740,h,lines)
for i in range(len(nodes)-1):d.arrow([(800,nodes[i][0]+nodes[i][1]),(800,nodes[i+1][0])])
d.box(490,1030,620,130,['生成時にG1〜G6を満たすか'],kind='amber',diamond=True)
d.arrow([(800,975),(800,1030)])
d.box(65,1240,690,120,['APPROPRIATE：記事を生成','C03予備・C10本命の2本'],kind='green')
d.box(845,1240,690,120,['INAPPROPRIATE：記事本文は作らない','C13・C17・C22本命/予備・C27予備の5組'],kind='red')
d.arrow([(490,1095),(410,1095),(410,1240)],'はい',(365,1170))
d.arrow([(1110,1095),(1190,1095),(1190,1240)],'いいえ',(1250,1170))
d.box(430,1450,740,110,['本チャットの照合と記録保存','入力・指示・応答原文・不適理由・確認所見'])
d.arrow([(410,1360),(410,1400),(700,1400),(700,1450)])
d.arrow([(1190,1360),(1190,1400),(900,1400),(900,1450)])
d.box(430,1650,740,125,['別モデルによる独立検証・採点：今回未実施','渡すもの：記事1本＋その3原文＋実際の生成指示','検証モデルも今回の実験では未指定'],kind='gray',dashed=True)
d.arrow([(65,1300),(30,1300),(30,1710),(430,1710)],'記事がある2組の今後の接続先',(225,1615),True)
d.text(800,1805,'当初のk=7から全記事入力へ拡大。今回は本命・予備も個別に実行し、自動切り替えは未実装。',20,color='#475569')
d.save('experiment-flow')

d=Diagram(1700,2330,'現行アプリ：生成・独立検証・1回修正の経路',
          '実装済みの処理を示す。今回の7組がこの全経路を実行済みという意味ではない。')
nodes=[(160,90,['① 条件を満たす原資料を取得・保存']),
       (290,90,['② PR TIMES企業IDごとに最新1記事を固定']),
       (420,90,['③ タイトル＋本文全体から埋め込みを計算']),
       (550,90,['④ UMAP → HDBSCANでクラスタリング']),
       (680,110,['⑤ 元ベクトルの重心に近い3記事を選択','AIなし／各クラスター1組／予備なし']),
       (840,100,['⑥ 固定した3原文＋生成指示で記事生成'])]
for y,h,lines in nodes:d.box(500,y,740,h,lines)
for i in range(len(nodes)-1):d.arrow([(870,nodes[i][0]+nodes[i][1]),(870,nodes[i+1][0])])
d.box(560,990,620,130,['生成本文が比較不適か'],kind='amber',diamond=True)
d.arrow([(870,940),(870,990)])
d.box(40,985,430,160,['即座に不適で確定','点数null','検証・修正を呼ばない'],kind='red')
d.arrow([(560,1055),(470,1055)],'はい',(515,1025))
d.box(500,1190,740,120,['⑦ 生成とは異なるモデルで個別検証','記事1本＋3原文＋実際の生成指示'])
d.arrow([(870,1120),(870,1190)],'いいえ',(935,1155))
d.box(560,1360,620,130,['初回判定が適切か'],kind='amber',diamond=True)
d.arrow([(870,1310),(870,1360)])
d.box(1270,1345,390,160,['初回判定を最終結果に','採否・点数・理由を保存'],kind='green')
d.arrow([(1180,1425),(1270,1425)],'はい',(1225,1388))
d.box(500,1570,740,110,['同じ生成モデルで1回だけ修正','同じ3原文・生成指示＋初稿・検証指摘'])
d.arrow([(870,1490),(870,1570)],'不適・要確認',(970,1527))
d.box(560,1730,620,130,['修正版が比較不適か'],kind='amber',diamond=True)
d.arrow([(870,1680),(870,1730)])
d.arrow([(560,1795),(255,1795),(255,1145)],'はい：即時不適へ',(260,1840))
d.box(500,1940,740,110,['同じ検証モデルで修正版を再検証','同じ3原文・実際の生成指示を再び渡す'])
d.arrow([(870,1860),(870,1940)],'いいえ',(935,1895))
d.box(500,2120,740,110,['再検証を最終結果にする','不適・要確認が残っても追加修正しない'],kind='green')
d.arrow([(870,2050),(870,2120)])
d.text(850,2285,'ノイズ・3記事未満は組を作らない。通信失敗は採否へ変換せず、保存済み成功は再開時に再送しない。',20,color='#475569')
d.save('implemented-pipeline-flow')

repo=Path(r'\\TRUENAS\dev\codex\newsWeave')
evidence=[]
for name in ['docs/seven-stage-system-design-20261015.md','app/pipeline.py','app/clustering.py','app/model_client.py','app/settings.py']:
    data=(repo/name).read_bytes()
    evidence.append({'repository_path':name,'sha256':hashlib.sha256(data).hexdigest()})
read=lambda p:json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
cluster_count=(read('outputs/C01-all13-selection-20261015/summary.json')['input_articles']+
    read('outputs/C02-all11-selection-20261015/summary.json')['input_articles']+
    read('outputs/C03-C10-allarticles-selection-20261015/summary.json')['totals']['input_articles']+
    read('outputs/C11-C30-allarticles-selection-20261015/summary.json')['totals']['articles'])
latest=read('outputs/promising-comparison-gpt61-sol-20261015/summary.json')
assert cluster_count==327
assert (latest['response_count'],latest['model_appropriate'],latest['model_inappropriate'])==(7,2,5)
(OUT/'basis.json').write_text(json.dumps({'confirmed_at':'2026-10-15','cluster_articles_in_full_input_experiments':327,
    'latest_generation':{'groups':7,'appropriate':2,'inappropriate':5,'model':'gpt-6.1-sol'},
    'independent_model_verification_performed_in_this_experiment':False,
    'diagrams':['experiment-flow.svg','implemented-pipeline-flow.svg'],
    'implementation_sources':evidence},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Saved 2 SVG diagrams, 2 PNG previews, and source/count verification.')
