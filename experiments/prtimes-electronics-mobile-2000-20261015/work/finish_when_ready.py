"""Continue directly to actual model selection once collection has committed 2000 sources."""
import sqlite3,time
from run_selection import DB,main,log

while True:
    connection=sqlite3.connect(DB)
    count=connection.execute('select count(*) from articles').fetchone()[0]
    connection.close()
    if count==2000:break
    if count>2000:raise ValueError('ARTICLE_COUNT_EXCEEDED')
    time.sleep(15)
log(stage='collection_ready_for_models',article_count=count)
main()
from finalize_outputs import main as finalize
finalize()
