import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime,timezone
from uuid import uuid4

def now():return datetime.now(timezone.utc).isoformat()
def dump(value):return json.dumps(value,ensure_ascii=False)

class Store:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,processing INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,role TEXT,text TEXT,created_at TEXT,response TEXT);
            CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY,session_id TEXT,status TEXT,created_at TEXT,artifact TEXT);
            CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,session_id TEXT,turn_id TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,session_id TEXT UNIQUE NOT NULL,document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plan_snapshots(plan_id TEXT,version INTEGER,document TEXT NOT NULL,PRIMARY KEY(plan_id,version));
            CREATE TABLE IF NOT EXISTS confirmations(request_id TEXT PRIMARY KEY,plan_id TEXT,version INTEGER,content_hash TEXT,response TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS monitoring(plan_id TEXT PRIMARY KEY,confirmed_version INTEGER NOT NULL,state TEXT NOT NULL,last_checked_at TEXT,next_check_at TEXT,lease_owner TEXT,lease_until TEXT);
            CREATE TABLE IF NOT EXISTS plan_checks(id TEXT PRIMARY KEY,plan_id TEXT,plan_version INTEGER,rule_id TEXT,request_id TEXT,payload TEXT NOT NULL,UNIQUE(plan_id,plan_version,rule_id,request_id));
            CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,plan_id TEXT,plan_version INTEGER,rule_id TEXT,check_id TEXT,created_at TEXT,text TEXT,delivery_status TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS checks_by_plan ON plan_checks(plan_id,plan_version,rule_id);
            CREATE TABLE IF NOT EXISTS check_runs(request_id TEXT PRIMARY KEY,plan_id TEXT,plan_version INTEGER,response TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS snapshots_no_update BEFORE UPDATE ON plan_snapshots BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
            CREATE TRIGGER IF NOT EXISTS snapshots_no_delete BEFORE DELETE ON plan_snapshots BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
            ''')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def create(self):
        sid=str(uuid4())
        with self.connect() as db:db.execute('INSERT INTO sessions(id,title,created_at) VALUES(?,?,?)',(sid,'Новая идея',now()))
        self.message(sid,'assistant','Расскажите о торговой идее: что хотите сделать и почему. Разберём основания, возражения и риск — без отправки заявок.')
        return self.state(sid)
    def message(self,sid,role,text,response=None):
        with self.connect() as db:db.execute('INSERT INTO messages(session_id,role,text,created_at,response) VALUES(?,?,?,?,?)',(sid,role,text,now(),dump(response) if response else None))
    def state(self,sid):
        with self.connect() as db:
            s=db.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
            if not s:return None
            messages=[dict(r) for r in db.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id',(sid,))]
            evidence=[json.loads(r[0]) for r in db.execute('SELECT payload FROM evidence WHERE session_id=? ORDER BY rowid',(sid,))]
        for m in messages:m['response']=json.loads(m['response']) if m['response'] else None
        return {'session':dict(s),'messages':messages,'evidence':evidence}
