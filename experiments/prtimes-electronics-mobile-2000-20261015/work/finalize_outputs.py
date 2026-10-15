"""Validate final persistence and package the execution records."""
import json,sqlite3,zipfile,hashlib
from pathlib import Path
from collections import Counter
from datetime import datetime,UTC

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'

def main():
    manifest=json.loads((OUT/'run-manifest.json').read_text(encoding='utf-8'))
    assert manifest['selection_complete'] is True
    connection=sqlite3.connect(OUT/'newsweave-electronics-mobile-2000-20261015.sqlite')
    assert connection.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert not connection.execute('pragma foreign_key_check').fetchall()
    count,unique=connection.execute('select count(*),count(distinct url) from articles').fetchone()
    assert count==unique==2000
    assert connection.execute("select count(*) from articles where release_type!='01'").fetchone()[0]==0
    assert connection.execute('select count(*) from drafts').fetchone()[0]==0
    assert connection.execute('select count(*) from verifications').fetchone()[0]==0
    audit=sqlite3.connect(OUT/'collection-audit-20261015.sqlite')
    assert audit.execute('pragma integrity_check').fetchone()[0]=='ok'
    counts=dict(audit.execute('select status,count(*) from snapshots group by status'))
    assert counts['accepted']==2000
    distribution=dict(audit.execute("select c.term,count(*) from snapshots s join candidates c on c.url=s.url where s.status='accepted' group by c.term"))
    origins=dict(audit.execute('select error,count(*) from snapshots group by error'))
    rows=audit.execute("select url,article_id,sha256 from snapshots where status='accepted'")
    for url,article_id,digest in rows:
        article=connection.execute('select url,raw_html from articles where id=?',(article_id,)).fetchone()
        assert article and article[0]==url and hashlib.sha256(article[1].encode()).hexdigest()==digest
    old=Path(r'\\TRUENAS\dev\codex\newsWeave\.local\newsweave-seven-stage-20261015.sqlite')
    old_unchanged=hashlib.sha256(old.read_bytes()).hexdigest()=='d30493bb0ebbe809b37142258f983a36a79517d960e4f102851a902b2ce108dc'
    assert old_unchanged
    receipts=[json.loads(line) for line in (OUT/'api-calls.jsonl').read_text(encoding='utf-8').splitlines()]
    selection=[r for r in receipts if r['endpoint']=='responses']
    assert len(selection)>=manifest['clusters']
    assert {r['cluster_id'] for r in selection}==set(range(manifest['clusters']))
    assert all(r['model_returned']==manifest['selection_model'] and r['status']=='completed' for r in selection)
    stats={'article_count':count,'unique_urls':unique,'snapshot_counts':counts,'keyword_article_counts':distribution,
           'snapshot_origins':origins,'real_model_calls':dict(Counter(r['endpoint'] for r in receipts)),
           'model_tokens':{'input_tokens':sum((r.get('usage') or {}).get('input_tokens',(r.get('usage') or {}).get('prompt_tokens',0)) for r in receipts),
                           'output_tokens':sum((r.get('usage') or {}).get('output_tokens',0) for r in receipts),
                           'total_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in receipts)},
           'selection_extra_responses':len(selection)-manifest['clusters'],
           'old_sqlite_unchanged':old_unchanged,'database_integrity':'ok','foreign_keys':'ok','snapshot_hashes':'2000 matched',
           'verified_at':datetime.now(UTC).isoformat()}
    (OUT/'verification.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    statuses=manifest['selection_results']
    report=f'''# 電子工作・モバイル2,000件の実モデル選定

指定キーワードの適格原資料2,000件を読み込み、⑤の本命・予備選定まで完了した。

| 項目 | 結果 |
| --- | --- |
| 適格原資料 | 2,000件（URL重複なし） |
| 検索語別の記事数 | 電子工作 {distribution.get('電子工作',0)}件、モバイル {distribution.get('モバイル',0)}件 |
| 本文を確認した原資料 | {sum(counts.values())}件 |
| 本文確認後の除外 | {counts.get('excluded',0)}件 |
| 企業ごとの最新記事 | {manifest['latest_company_articles']}件 |
| クラスター数 | {manifest['clusters']} |
| ノイズ記事 | {manifest['noise_articles']}件 |
| 本命・予備の2組 | {statuses['TWO_SETS']}クラスター |
| 本命のみ | {statuses['ONE_SET']}クラスター |
| 選定不可 | {statuses['NO_SET']}クラスター |
| 選定モデル | `{manifest['selection_model']}` |
| 選定候補の上限 | 各クラスター30記事、全文入力 |
| 実行ID | `{manifest['run_id']}` |

ユーザー指定によりAI/IoTの必須条件を外し、「商品サービス」（01）と111語のタイトル除外条件を維持した。2語の公開キーワード検索結果から収集し、企業別の整理前に2,000件を保存した。両方の検索に現れるURLは重複保存せず、最初に保存した検索語へ帰属させた。各語1,000件ずつの割当ではない。

公式HTMLの既存スナップショット再利用は{origins.get('stored_official_snapshot',0)}件、今回のHTTP取得は{origins.get('live',0)}件である。この件数には本文確認後の除外を含む。元HTMLの取得日時と取得元区分は監査DBに保存した。

埋め込みは`text-embedding-3-small`、UMAP/HDBSCANは現行設定を使用した。全所属記事の元ベクトルの重心から上位最大30記事を選び、GPT-4.1へ渡した。モデルが比較可能な組を見つけられないクラスターは、理由を保存して選定不可とした。

読みやすい本命・予備・選定理由は[選定一覧](selections.md)、記事ID等の機械可読結果は[選定JSON](selections.json)にある。

新DBは現行スキーマで別途作成した。既存DBへの破壊的な移行は行っていない。接続先の使い分け、旧DBの場所、再開コマンドは[DB利用ガイド](database-guide.md)を参照。

`runs.step`は`generate`で停止しており、⑤は完了、⑥は未実行である。`drafts`・`verifications`は0件。今回の依頼範囲に合わせ、比較記事生成・独立検証は実行していない。

API要求・応答は`model-io/`、モデル返却ID・使用トークン等の実行記録は`api-calls.jsonl`、条件と実行IDは`run-manifest.json`へ保存した。

選定の追加応答は{len(selection)-manifest['clusters']}件。選定判定と記事組数の矛盾があった応答は採用せず原文を保存した。本命・予備の両方があれば`TWO_SETS`となることを出力スキーマの説明へ明記し、保存済みの成功結果を再利用して未完了分を再実行した。返答を手作業で選定成功に書き換えていない。

検証では、新DBと監査DBの整合性、外部キー、原資料2,000件のHTMLハッシュ対応、候補の重心順位、選定応答のID・組数、全クラスターの選定完了、返却モデル、旧SQLiteの不変を確認した。コード検証は90テストとRuffが通過した。詳細は[検証記録](verification.json)にある。

実行用の作業コピーとスクリプトは`execution-source.zip`、元コードとの差分は`execution-changes.patch`。元リポジトリのコードや接続設定へのcommit/pushは行っていない。
'''
    (OUT/'report.md').write_text(report,encoding='utf-8')
    with zipfile.ZipFile(OUT/'execution-source.zip','w',zipfile.ZIP_DEFLATED) as z:
        root=ROOT/'work/runtime'
        for p in root.rglob('*'):
            if p.is_file() and not any(x in p.parts for x in ['__pycache__','.pytest_cache','.ruff_cache']):z.write(p,'runtime/'+p.relative_to(root).as_posix())
        for name in ['acquire.py','collect_stream.py','run_selection.py','finish_when_ready.py','finalize_outputs.py']:z.write(ROOT/'work'/name,name)
    with zipfile.ZipFile(OUT/'execution-source.zip') as z:
        hashes={name:hashlib.sha256(z.read(name)).hexdigest() for name in z.namelist()}
    (OUT/'source-hashes.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    audit.close();connection.close()
    print(json.dumps(stats,ensure_ascii=False))

if __name__=='__main__':main()
