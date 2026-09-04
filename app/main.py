from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import sqlite3, json, asyncio, random, uuid, math
from datetime import datetime, timezone
import numpy as np
from .risk_engine import RiskEngine, FEATURE_NAMES

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'data' / 'riskshield.db'
STATIC = Path(__file__).resolve().parent / 'static'
engine = RiskEngine()
app = FastAPI(title='RiskShield AI', version='1.0.0')
app.mount('/static', StaticFiles(directory=STATIC), name='static')

class ScoreRequest(BaseModel):
    customer_id: str = 'CUS-DEMO-001'
    amount: float = Field(1200, ge=1)
    account_age_days: int = Field(180, ge=0)
    transactions_last_1h: int = Field(2, ge=0)
    failed_attempts_1h: int = Field(0, ge=0)
    average_transaction_amount: float = Field(900, ge=0)
    device_changes_24h: int = Field(0, ge=0)
    location_changes_24h: int = Field(0, ge=0)
    previous_chargebacks: int = Field(0, ge=0)
    previous_refunds: int = Field(0, ge=0)
    payment_method: str = 'upi'
    customer_transaction_frequency: float = Field(2.0, ge=0)
    time_since_previous_transaction_min: float = Field(180, ge=0)

class ActionRequest(BaseModel):
    action: str


def db():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c=db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS transactions(
      id TEXT PRIMARY KEY, created_at TEXT, customer_id TEXT, amount REAL,
      payment_method TEXT, risk_score REAL, risk_level TEXT, decision TEXT,
      label INTEGER, factors TEXT, status TEXT DEFAULT 'open'
    );
    CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT, created_at TEXT, action TEXT, actor TEXT DEFAULT 'risk-engine');
    ''')
    c.commit(); c.close()
init_db()

@app.get('/')
def index(): return FileResponse(STATIC/'index.html')

@app.get('/api/v1/health')
def health(): return {'status':'ok','model_version':engine.model_version,'demo_mode':True}

@app.get('/api/v1/metrics')
def metrics(): return engine.metrics

@app.get('/api/v1/model')
def model(): return {'model_version':engine.model_version,'model_type':'RandomForestClassifier','features':FEATURE_NAMES,'dataset':engine.dataset_info,'thresholds':engine.thresholds}

@app.get('/api/v1/analytics')
def analytics():
    c=db(); rows=c.execute('SELECT * FROM transactions ORDER BY created_at DESC LIMIT 1000').fetchall(); c.close()
    n=len(rows); high=sum(r['risk_level']=='HIGH' for r in rows); med=sum(r['risk_level']=='MEDIUM' for r in rows); low=sum(r['risk_level']=='LOW' for r in rows)
    volume=sum(r['amount'] for r in rows); blocked=sum(r['amount'] for r in rows if r['decision']!='ALLOW')
    return {'total_transactions':n,'high_risk':high,'medium_risk':med,'low_risk':low,'volume':round(volume,2),'estimated_exposure':round(blocked,2),'false_positive_cost':engine.metrics['false_positive_cost_demo'],'risk_distribution':{'HIGH':high,'MEDIUM':med,'LOW':low}}

@app.get('/api/v1/transactions')
def transactions(limit:int=100, risk:str|None=None, q:str|None=None):
    c=db(); sql='SELECT * FROM transactions WHERE 1=1'; args=[]
    if risk: sql+=' AND risk_level=?'; args.append(risk.upper())
    if q: sql+=' AND (id LIKE ? OR customer_id LIKE ? OR payment_method LIKE ?)'; args += [f'%{q}%']*3
    sql+=' ORDER BY created_at DESC LIMIT ?'; args.append(min(limit,500))
    rows=c.execute(sql,args).fetchall(); c.close()
    return [dict(r) | {'factors':json.loads(r['factors'])} for r in rows]

@app.get('/api/v1/transactions/{txid}')
def transaction(txid:str):
    c=db(); r=c.execute('SELECT * FROM transactions WHERE id=?',(txid,)).fetchone(); c.close()
    if not r: raise HTTPException(404,'Transaction not found')
    return dict(r) | {'factors':json.loads(r['factors'])}

@app.get('/api/v1/audit')
def audit(limit:int=100):
    c=db(); rows=c.execute('SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?', (min(limit,500),)).fetchall(); c.close(); return [dict(r) for r in rows]

@app.get('/api/v1/alerts')
def alerts():
    c=db(); rows=c.execute("SELECT * FROM transactions WHERE risk_level='HIGH' AND status='open' ORDER BY created_at DESC LIMIT 100").fetchall(); c.close()
    return [dict(r)|{'factors':json.loads(r['factors'])} for r in rows]

@app.post('/api/v1/risk/score')
def score(req:ScoreRequest):
    payload=req.model_dump(); result=engine.score(payload)
    txid='TX-'+uuid.uuid4().hex[:10].upper(); now=datetime.now(timezone.utc).isoformat()
    save_transaction(txid,now,payload,result,label=None)
    return {'transaction_id':txid,**result}

def save_transaction(txid,now,payload,result,label):
    c=db(); c.execute('INSERT OR REPLACE INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?)',(
      txid,now,payload['customer_id'],payload['amount'],payload['payment_method'],result['risk_score'],result['risk_level'],result['decision'],label,json.dumps(result['factors']),'open'))
    c.execute('INSERT INTO audit_logs(transaction_id,created_at,action) VALUES(?,?,?)',(txid,now,'SCORED'))
    c.commit(); c.close()

@app.post('/api/v1/transactions/{txid}/action')
def action(txid:str, req:ActionRequest):
    allowed={'ALLOW','VERIFY','MANUAL REVIEW','RESOLVE','DISMISS'}
    if req.action.upper() not in allowed: raise HTTPException(400,'Unsupported workflow action')
    c=db(); r=c.execute('SELECT id FROM transactions WHERE id=?',(txid,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Transaction not found')
    status='closed' if req.action.upper() in {'RESOLVE','DISMISS','ALLOW'} else 'open'
    now=datetime.now(timezone.utc).isoformat(); c.execute('UPDATE transactions SET status=? WHERE id=?',(status,txid)); c.execute('INSERT INTO audit_logs(transaction_id,created_at,action,actor) VALUES(?,?,?,?)',(txid,now,req.action.upper(),'operator')); c.commit(); c.close(); return {'ok':True,'transaction_id':txid,'action':req.action.upper(),'status':status}

@app.post('/api/v1/simulator/reset')
def reset():
    c=db(); c.execute('DELETE FROM transactions'); c.execute('DELETE FROM audit_logs'); c.commit(); c.close(); return {'ok':True}

@app.websocket('/ws/transactions')
async def websocket(ws:WebSocket):
    await ws.accept();
    try:
        while True:
            msg=await ws.receive_json()
            cmd=msg.get('command','start')
            if cmd=='start':
                speed=float(msg.get('speed',1.0)); speed=max(.2,min(4,speed))
                while True:
                    tx=engine.generate_transaction()
                    now=datetime.now(timezone.utc).isoformat(); txid='TX-'+uuid.uuid4().hex[:10].upper(); result=engine.score(tx)
                    save_transaction(txid,now,tx,result,tx.get('label'))
                    event={'transaction_id':txid,'created_at':now,**tx,**result}
                    await ws.send_json(event)
                    try:
                        control=await asyncio.wait_for(ws.receive_json(),timeout=max(.3,1.6/speed))
                        if control.get('command')=='pause': break
                        if control.get('command')=='reset': reset(); break
                        speed=float(control.get('speed',speed)); speed=max(.2,min(4,speed))
                    except asyncio.TimeoutError: pass
            elif cmd=='score':
                payload=msg.get('transaction',{}); result=engine.score(payload); txid='TX-'+uuid.uuid4().hex[:10].upper(); now=datetime.now(timezone.utc).isoformat(); save_transaction(txid,now,payload,result,None); await ws.send_json({'transaction_id':txid,'created_at':now,**payload,**result})
    except WebSocketDisconnect: pass
    except Exception:
        try: await ws.close()
        except Exception: pass
