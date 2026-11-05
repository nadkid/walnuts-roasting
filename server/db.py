"""SQLite connections; every mutation owns a serialized immediate transaction."""
import sqlite3, json, os, uuid
from pathlib import Path
from contextlib import contextmanager
ROOT=Path(__file__).resolve().parent.parent

def uid(): return uuid.uuid4().hex

def connect(path):
    db=sqlite3.connect(path,timeout=15,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    return db

@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise

def migrate(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    db=connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY)')
    for f in sorted((ROOT/'migrations').glob('*.sql')):
        if not db.execute('SELECT 1 FROM migrations WHERE name=?',(f.name,)).fetchone():
            db.executescript('BEGIN IMMEDIATE;\n'+f.read_text()+"\nINSERT INTO migrations VALUES ('"+f.name+"');\nCOMMIT;")
    defaults={'timezone':'Asia/Tokyo','charge_mg':1200000,'max_charge_mg':0,'roast_days':[0,1,2,3,4,5,6], 'roast_days_confirmed':False,'buffer_days':0,'safety_bp':0,'channel_priority':['dispatch','brew','retail'],'eligible_payments':['PAID'],'pos':'Square','cutover_at':None,'poll_seconds':900,'brand_color':'#334c3d','demo':False}
    with transaction(db):
        for k,v in defaults.items(): db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(k,json.dumps(v)))
        for id,name in [('roastery','Roastery'),('cafe','Café'),('wall','Retail wall'),('packing','Packing area')]: db.execute('INSERT OR IGNORE INTO locations VALUES (?,?)',(id,name))
    db.close()
    os.chmod(path,0o600)

def settings(db): return {r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}
def rows(db,sql,args=()): return [dict(r) for r in db.execute(sql,args)]
def one(db,sql,args=()):
    r=db.execute(sql,args).fetchone()
    if r is None: raise ValueError('Record not found. Refresh and try again.')
    return dict(r)
