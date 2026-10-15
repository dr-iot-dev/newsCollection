"""Checkpointed public keyword collection. Never changes existing databases."""
import sys,json,sqlite3,hashlib,argparse
from pathlib import Path
from datetime import datetime,UTC
from urllib.parse import urlencode,urljoin
sys.path.insert(0,str(Path(__file__).parent/'runtime'))
from app.acquisition import Collector,parse_article,save_article,exclusions_from,title_excluded
from app.db import open_session
from app.http import CollectionError

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'
DB=OUT/'newsweave-electronics-mobile-2000-20261015.sqlite'
AUDIT=OUT/'collection-audit-20261015.sqlite'

def log(**data):
    data={'time':datetime.now(UTC).isoformat(),**data}
    line=json.dumps(data,ensure_ascii=False)
    with (OUT/'progress.jsonl').open('a',encoding='utf-8') as f:f.write(line+'\n')
    print(line,flush=True)
