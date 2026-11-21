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
