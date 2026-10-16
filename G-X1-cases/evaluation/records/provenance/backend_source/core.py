"""Identity-bound durable queue. No API or scientific dependencies."""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

TASKS = ('G1', 'G2', 'G3', 'X1', 'X2', 'X3')
MODEL = 'Qwen/Qwen3-8B'
TERMINAL = ('HISTORICAL', 'COMPLETE', 'SCORING_REVIEW')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def identity_key(row):
    return digest({k: row[k] for k in ('case_uid','task','messages_sha256','science_sha256')})


def compatible_history(current, prior, answer):
    binding=answer.get('binding') or {};metadata=answer.get('_case_metadata') or {}
    for info in (binding,metadata):
        for key in ('case_uid','task','messages_sha256'):
            if key in info and info[key]!=current[key]:return False
    return (answer.get('model') == MODEL and answer.get('status') == 'RESPONSE_RECEIVED'
            and answer.get('case_uid') == current['case_uid']
            and 'raw_completion' in answer and isinstance(answer['raw_completion'], str)
            and identity_key(current) == identity_key(prior))


class ProcessLock:
    """OS-held byte lock; automatically released by the OS on process death."""
    def __init__(self, path): self.path = Path(path); self.file = None
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0: self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close(); self.file = None
            raise RuntimeError('Task is already owned by another process') from exc
        return self
    def __exit__(self, *args):
        if self.file:
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close(); self.file = None


class Queue:
    def __init__(self, path, task):
        if task not in TASKS: raise ValueError('Unknown task')
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.task=task
        with self.connect() as q:
            q.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS cases(
                    uid TEXT PRIMARY KEY, identity_key TEXT NOT NULL, record TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    retry_after REAL NOT NULL DEFAULT 0, owner TEXT,
                    answer_path TEXT, result TEXT, error TEXT, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, time REAL NOT NULL, uid TEXT, kind TEXT, detail TEXT);
            ''')
            if 'retry_base' not in {r[1] for r in q.execute('PRAGMA table_info(cases)')}:
                q.execute('ALTER TABLE cases ADD COLUMN retry_base INTEGER NOT NULL DEFAULT 0')
            q.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',('task',task))
            if q.execute("SELECT value FROM settings WHERE key='task'").fetchone()[0] != task:
                raise ValueError('Queue belongs to another task')

    @contextlib.contextmanager
    def connect(self):
        q=sqlite3.connect(self.path,timeout=30);q.row_factory=sqlite3.Row
        q.execute('PRAGMA synchronous=FULL');q.execute('PRAGMA busy_timeout=30000')
        try:
            yield q; q.commit()
        except BaseException:
            q.rollback();raise
        finally:q.close()

    def add_cases(self, rows):
        with self.connect() as q:
            q.execute('BEGIN IMMEDIATE')
            for row in rows:
                if row['task'] != self.task: raise ValueError('Task mismatch')
                sig=identity_key(row);old=q.execute('SELECT identity_key FROM cases WHERE uid=?',(row['case_uid'],)).fetchone()
                if old and old[0]!=sig:raise ValueError('Existing case identity changed: '+row['case_uid'])
                q.execute('INSERT OR IGNORE INTO cases(uid,identity_key,record,status,updated) VALUES(?,?,?,?,?)',
                          (row['case_uid'],sig,json.dumps(row,ensure_ascii=False),'PENDING' if row.get('evaluation_eligible',True) else 'EXCLUDED',time.time()))

    def setting(self,key,value=None):
        with self.connect() as q:
            if value is not None:q.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))
            r=q.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return json.loads(r[0]) if r else None

    def event(self, uid, kind, detail=None):
        with self.connect() as q:q.execute('INSERT INTO events(time,uid,kind,detail) VALUES(?,?,?,?)',(time.time(),uid,kind,json.dumps(detail,ensure_ascii=False)))

    def get(self, uid):
        with self.connect() as q:
            r=q.execute('SELECT * FROM cases WHERE uid=?',(uid,)).fetchone()
            return dict(r) if r else None

    def rows(self, statuses=None):
        with self.connect() as q:
            sql='SELECT * FROM cases';args=[]
            if statuses:
                sql+=' WHERE status IN ('+','.join('?' for _ in statuses)+')';args=list(statuses)
            return [dict(r) for r in q.execute(sql+' ORDER BY uid',args)]

    def claim(self, owner='test', max_attempts=3):
        with self.connect() as q:
            q.execute('BEGIN IMMEDIATE')
            control=q.execute("SELECT value FROM settings WHERE key='control'").fetchone()
            if control and json.loads(control[0]).get('stop'):return None
            row=q.execute("SELECT * FROM cases WHERE status IN ('PENDING','RETRY') AND attempts-retry_base<? AND retry_after<=? ORDER BY rowid LIMIT 1",(max_attempts,time.time())).fetchone()
            if not row:return None
            q.execute("UPDATE cases SET status='RUNNING',attempts=attempts+1,owner=?,updated=? WHERE uid=?",(owner,time.time(),row['uid']))
            rec=json.loads(row['record']);rec['_attempt']=row['attempts']+1;rec['_owner']=owner
            rec['_budget_attempt']=row['attempts']-row['retry_base']+1
            return rec

    def complete(self,uid,status,answer,answer_path=None):
        if status not in TERMINAL:raise ValueError('Not a response state')
        with self.connect() as q:
            q.execute("UPDATE cases SET status=?,result=?,answer_path=COALESCE(?,answer_path),error=NULL,updated=? WHERE uid=? AND status NOT IN ('HISTORICAL','COMPLETE')",
                      (status,json.dumps(answer,ensure_ascii=False,default=str),str(answer_path) if answer_path else None,time.time(),uid))

    def fail(self,uid,status,error,retry_after=0):
        if status not in ('RETRY','DEFERRED','PROVIDER_PAUSED','NEEDS_REVIEW','PENDING'):raise ValueError('Invalid failure state')
        with self.connect() as q:
            q.execute("UPDATE cases SET status=?,error=?,retry_after=?,updated=? WHERE uid=? AND status NOT IN ('HISTORICAL','COMPLETE','SCORING_REVIEW')",(status,str(error),retry_after,time.time(),uid))

    def recover_raw(self,uid,path):
        answer=read_json(path);row=self.get(uid)
        if (not row or answer.get('case_uid')!=uid or answer.get('model')!=MODEL
            or answer.get('identity_key')!=row['identity_key']
            or answer.get('status')!='RESPONSE_RECEIVED' or not isinstance(answer.get('raw_completion'),str)):
            raise ValueError('Unbound response artifact')
        answer['result']={'category':'SCORING_ERROR','reason':'RECOVERED_NEEDS_LOCAL_GRADING'}
        self.complete(uid,'SCORING_REVIEW',answer,path)

    def summary(self):
        with self.connect() as q:
            counts=dict(q.execute('SELECT status,COUNT(*) FROM cases GROUP BY status'))
            cats={}
            for r in q.execute("SELECT result FROM cases WHERE status IN ('HISTORICAL','COMPLETE','SCORING_REVIEW')"):
                c=json.loads(r[0]).get('result',{}).get('category','UNSCORED');cats[c]=cats.get(c,0)+1
        return {'task':self.task,'total':sum(counts.values()),'counts':counts,'categories':cats,'control':self.setting('control') or {}}
