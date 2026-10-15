"""Read search pages as needed until 2000 product/service sources are saved."""
from acquire import *
from app.models import Article
from sqlalchemy import select,func

def main():
    audit=sqlite3.connect(AUDIT);audit.row_factory=sqlite3.Row
    audit.executescript('''
    CREATE TABLE IF NOT EXISTS search_pages(term TEXT,page INTEGER,url TEXT,payload TEXT,fetched_at TEXT,PRIMARY KEY(term,page));
    CREATE TABLE IF NOT EXISTS candidates(url TEXT PRIMARY KEY,term TEXT,page INTEGER,position INTEGER,title TEXT,metadata TEXT);
    CREATE TABLE IF NOT EXISTS snapshots(url TEXT PRIMARY KEY,html TEXT,sha256 TEXT,fetched_at TEXT,status TEXT,article_id TEXT,error TEXT);
    ''')
    session=open_session('sqlite:///'+DB.as_posix())
    collector=Collector(exclusions_from(Path(__file__).parent/'runtime/app/title-exclusions.txt'))
    cache_path=Path(r'\\TRUENAS\dev\codex\newsWeave\.local\extraction-1000-20261013\collection-audit.sqlite')
    cache=sqlite3.connect('file:////'+str(cache_path)[2:].replace('\\','/')+'?mode=ro',uri=True)
    index={r[0]:r[1] for r in cache.execute('select final_url,id from raw_snapshots where status_code=200')}
    accepted=session.scalar(select(func.count()).select_from(Article))
    done=audit.execute('select count(*) from snapshots').fetchone()[0]
    for page in range(1,251):
        for term in ['電子工作','モバイル']:
            if accepted>=2000:break
            last=audit.execute('select payload from search_pages where term=? order by page desc limit 1',(term,)).fetchone()
            if last and page>json.loads(last[0])['data']['last_page']:continue
            prior=audit.execute('select payload from search_pages where term=? and page=?',(term,page)).fetchone()
            if prior:payload=json.loads(prior[0])
            else:
                url='https://prtimes.jp/api/keyword_search.php/search?'+urlencode({'keyword':term,'page':page,'limit':40})
                payload=json.loads(collector.get(url).body)
                if payload.get('status')!=200 or payload['data']['current_page']!=page:raise ValueError('SEARCH_RESPONSE_SCHEMA')
                audit.execute('insert into search_pages values(?,?,?,?,?)',(term,page,url,json.dumps(payload,ensure_ascii=False),datetime.now(UTC).isoformat()));audit.commit()
            for position,item in enumerate(payload['data']['release_list']):
                url=urljoin('https://prtimes.jp',item['release_url'])
                audit.execute('insert or ignore into candidates values(?,?,?,?,?,?)',(url,term,page,position,item['title'],json.dumps(item,ensure_ascii=False)))
            audit.commit()
            rows=audit.execute('select * from candidates where term=? and page=? order by position',(term,page)).fetchall()
            for row in rows:
                if accepted>=2000:break
                url=row['url']
                if audit.execute('select 1 from snapshots where url=?',(url,)).fetchone():continue
                if title_excluded(row['title'],collector.exclusions):continue
                origin='live'
                try:
                    if url in index:
                        html,stamp=cache.execute('select body_text,fetched_at from raw_snapshots where id=?',(index[url],)).fetchone()
                        origin='stored_official_snapshot'
                    else:
                        response=collector.get(url);html=response.body.decode('utf-8');stamp=datetime.now(UTC).isoformat()
                    data=parse_article(url,html,collector.exclusions,require_domain=False)
                    article_id=None
                    if data:
                        old=session.scalar(select(Article).where(Article.url==url,Article.snapshot_hash==data['snapshot_hash']))
                        article=save_article(session,data);session.commit();article_id=article.id
                        if old is None:accepted+=1
                    audit.execute('insert into snapshots values(?,?,?,?,?,?,?)',(url,html,hashlib.sha256(html.encode()).hexdigest(),stamp,'accepted' if data else 'excluded',article_id,origin));audit.commit();done+=1
                except (CollectionError,ValueError) as exc:
                    session.rollback();code=getattr(exc,'code',str(exc))
                    log(stage='acquisition_error',url=url,code=code)
                    if code in {'ROBOTS_DISALLOWED','ROBOTS_INVALID','DNS_ERROR','DNS_ADDRESS_BLOCKED'}:raise
                    continue
                if done%25==0:
                    log(stage='collect',page=page,read=done,counts=dict(audit.execute('select status,count(*) from snapshots group by status').fetchall()))
        if accepted>=2000:break
    log(stage='collection_complete',read=done,accepted=accepted,target=2000,counts=dict(audit.execute('select status,count(*) from snapshots group by status').fetchall()))
    collector.close();cache.close();session.close();audit.close()
    if accepted!=2000:raise ValueError('KEYWORD_SEARCH_EXHAUSTED_BEFORE_TARGET')

if __name__=='__main__':main()
