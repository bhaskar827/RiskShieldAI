from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import sqlite3, json, asyncio, random, uuid, hmac, hashlib, os
from datetime import datetime, timezone
import numpy as np
from .risk_engine import RiskEngine, FEATURE_NAMES

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'data' / 'riskshield.db'
STATIC = Path(__file__).resolve().parent / 'static'
engine = RiskEngine()
app = FastAPI(title='RiskShield AI', version='1.1.0')
app.mount('/static', StaticFiles(directory=STATIC), name='static')

WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET', '').strip()
DEMO_MODE = os.getenv('DEMO_MODE', 'false').strip().lower() == 'true'
DEMO_EVENT_KEY = os.getenv('DEMO_EVENT_KEY', '').strip()

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

clients = set()


def db():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS transactions(
      id TEXT PRIMARY KEY, created_at TEXT, customer_id TEXT, amount REAL,
      payment_method TEXT, risk_score REAL, risk_level TEXT, decision TEXT,
      label INTEGER, factors TEXT, status TEXT DEFAULT 'open',
      source TEXT DEFAULT 'simulation', provider_id TEXT, event_type TEXT,
      currency TEXT DEFAULT 'INR'
    );
    CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT, created_at TEXT, action TEXT, actor TEXT DEFAULT 'risk-engine');''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS webhook_events(
        provider_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        received_at TEXT NOT NULL,
        PRIMARY KEY(provider_id, event_type)
    )

    ''')
    # Upgrade databases created by v1.0.
    cols = {r['name'] for r in c.execute('PRAGMA table_info(transactions)').fetchall()}
    for name, definition in [('source', "TEXT DEFAULT 'simulation'"), ('provider_id', 'TEXT'), ('event_type', 'TEXT'), ('currency', "TEXT DEFAULT 'INR'")]:
        if name not in cols:
            c.execute(f'ALTER TABLE transactions ADD COLUMN {name} {definition}')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_provider_event ON transactions(provider_id, event_type)')
    c.commit(); c.close()

init_db()

@app.get('/')
def index(): return FileResponse(STATIC/'index.html')

@app.get('/api/v1/health')
def health():
    return {'status':'ok','model_version':engine.model_version,'mode':'server_live','razorpay_webhook_configured':bool(WEBHOOK_SECRET),'demo_event_enabled':DEMO_MODE}

@app.get('/api/v1/metrics')
def metrics(): return engine.metrics

@app.get('/api/v1/model')
def model():
    return {'model_version':engine.model_version,'model_type':'RandomForestClassifier','features':FEATURE_NAMES,'dataset':engine.dataset_info,'thresholds':engine.thresholds}

@app.get('/api/v1/analytics')
def analytics():
    c=db(); rows=c.execute('SELECT * FROM transactions ORDER BY created_at DESC LIMIT 1000').fetchall(); c.close()
    n=len(rows); high=sum(r['risk_level']=='HIGH' for r in rows); med=sum(r['risk_level']=='MEDIUM' for r in rows); low=sum(r['risk_level']=='LOW' for r in rows)
    volume=sum(r['amount'] for r in rows); blocked=sum(r['amount'] for r in rows if r['decision']!='ALLOW')
    live=sum((r['source'] or '')=='razorpay' for r in rows)
    return {'total_transactions':n,'high_risk':high,'medium_risk':med,'low_risk':low,'volume':round(volume,2),'estimated_exposure':round(blocked,2),'false_positive_cost':engine.metrics['false_positive_cost_demo'],'risk_distribution':{'HIGH':high,'MEDIUM':med,'LOW':low},'razorpay_transactions':live}

@app.get('/api/v1/transactions')
def transactions(
    limit: int = 100,
    risk: str | None = None,
    q: str | None = None,
    source: str | None = None
):
    c = db()

    sql = 'SELECT * FROM transactions WHERE 1=1'
    args = []

    if risk:
        sql += ' AND risk_level=?'
        args.append(risk.upper())

    if source:
        sql += ' AND source=?'
        args.append(source.lower())

    if q:
        sql += '''
            AND (
                id LIKE ?
                OR customer_id LIKE ?
                OR payment_method LIKE ?
                OR provider_id LIKE ?
            )
        '''
        args += [f'%{q}%'] * 4

    sql += ' ORDER BY created_at DESC LIMIT ?'
    args.append(min(limit, 500))

    rows = c.execute(sql, args).fetchall()
    c.close()

    result = []

    for r in rows:
        item = dict(r)

        # Convert Razorpay lifecycle event into
        # a clear payment status for the frontend.
        event_type = item.get('event_type')

        if event_type == 'payment.captured':
            item['payment_status'] = 'CAPTURED'

        elif event_type == 'payment.authorized':
            item['payment_status'] = 'AUTHORIZED'

        elif event_type == 'payment.failed':
            item['payment_status'] = 'FAILED'

        else:
            item['payment_status'] = (
                item.get('status') or 'UNKNOWN'
            ).upper()

        item['factors'] = json.loads(
            item.get('factors') or '[]'
        )

        result.append(item)

    return result
@app.get('/api/v1/transactions/{txid}')
def transaction(txid: str):
    c = db()

    r = c.execute(
        'SELECT * FROM transactions WHERE id=?',
        (txid,)
    ).fetchone()

    c.close()

    if not r:
        raise HTTPException(
            404,
            'Transaction not found'
        )

    item = dict(r)

    event_type = item.get('event_type')

    if event_type == 'payment.captured':
        item['payment_status'] = 'CAPTURED'

    elif event_type == 'payment.authorized':
        item['payment_status'] = 'AUTHORIZED'

    elif event_type == 'payment.failed':
        item['payment_status'] = 'FAILED'

    else:
        item['payment_status'] = (
            item.get('status') or 'UNKNOWN'
        ).upper()

    item['factors'] = json.loads(
        item.get('factors') or '[]'
    )

    return item
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
    save_transaction(txid,now,payload,result,label=None,source='api',provider_id=None,event_type='manual_score')
    return {'transaction_id':txid,**result}


def save_transaction(
    txid,
    now,
    payload,
    result,
    label,
    source='simulation',
    provider_id=None,
    event_type=None,
    currency='INR'
):
    c = db()

    existing = None

    if provider_id:
        existing = c.execute(
            'SELECT id FROM transactions WHERE provider_id=?',
            (provider_id,)
        ).fetchone()

    # Map Razorpay lifecycle event to actual payment status
    if event_type == 'payment.captured':
        payment_status = 'CAPTURED'
    elif event_type == 'payment.authorized':
        payment_status = 'AUTHORIZED'
    elif event_type == 'payment.failed':
        payment_status = 'FAILED'
    else:
        payment_status = 'OPEN'

    if existing:
        txid = existing['id']

        c.execute(
            """
            UPDATE transactions SET
                created_at=?,
                customer_id=?,
                amount=?,
                payment_method=?,
                risk_score=?,
                risk_level=?,
                decision=?,
                label=?,
                factors=?,
                status=?,
                source=?,
                provider_id=?,
                event_type=?,
                currency=?
            WHERE id=?
            """,
            (
                now,
                payload['customer_id'],
                payload['amount'],
                payload['payment_method'],
                result['risk_score'],
                result['risk_level'],
                result['decision'],
                label if label is not None else result.get('label', 'UNKNOWN'),
                json.dumps(result['factors']),
                payment_status,
                source,
                provider_id,
                event_type,
                currency,
                txid
            )
        )

        created = False

    else:
        c.execute(
            """
            INSERT INTO transactions
            (
                id,
                created_at,
                customer_id,
                amount,
                payment_method,
                risk_score,
                risk_level,
                decision,
                label,
                factors,
                status,
                source,
                provider_id,
                event_type,
                currency
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                txid,
                now,
                payload['customer_id'],
                payload['amount'],
                payload['payment_method'],
                result['risk_score'],
                result['risk_level'],
                result['decision'],
                label if label is not None else result.get('label', 'UNKNOWN'),
                json.dumps(result['factors']),
                payment_status,
                source,
                provider_id,
                event_type,
                currency
            )
        )

        created = True

    c.execute(
        """
        INSERT INTO audit_logs
        (transaction_id, created_at, action, actor)
        VALUES(?,?,?,?)
        """,
        (
            txid,
            now,
            'SCORED',
            source
        )
    )

    c.commit()
    c.close()

    return txid, created
def customer_features(customer_id, amount, now_iso):
    c=db(); rows=c.execute('SELECT * FROM transactions WHERE customer_id=? ORDER BY created_at DESC LIMIT 200',(customer_id,)).fetchall(); c.close()
    if not rows:
        return {'account_age_days':180,'transactions_last_1h':0,'failed_attempts_1h':0,'average_transaction_amount':max(amount,900),'device_changes_24h':0,'location_changes_24h':0,'previous_chargebacks':0,'previous_refunds':0,'customer_transaction_frequency':1.0,'time_since_previous_transaction_min':180}
    amounts=[float(r['amount']) for r in rows]
    try:
        last=datetime.fromisoformat(rows[0]['created_at'].replace('Z','+00:00'))
        now=datetime.fromisoformat(now_iso.replace('Z','+00:00'))
        gap=max(0,(now-last).total_seconds()/60)
    except Exception:
        gap=180
    account_age=180
    # Historical transaction counts become velocity signals; no unavailable device/location data is invented.
    return {'account_age_days':account_age,'transactions_last_1h':sum(1 for r in rows if gap <= 60),'failed_attempts_1h':sum(1 for r in rows if r['event_type']=='payment.failed' and gap <= 60),'average_transaction_amount':float(np.mean(amounts)),'device_changes_24h':0,'location_changes_24h':0,'previous_chargebacks':sum(1 for r in rows if r['event_type']=='payment.dispute.created'),'previous_refunds':sum(1 for r in rows if r['event_type'] in {'refund.created','payment.refunded'}),'customer_transaction_frequency':len(rows)/max(1,30),'time_since_previous_transaction_min':gap}


def pseudonymous_customer(payment):
    notes=payment.get('notes') or {}
    if isinstance(notes, list):
        notes={}
    if notes.get('customer_id'):
        return str(notes['customer_id'])[:64]
    raw=str(payment.get('email') or payment.get('contact') or payment.get('id') or 'unknown')
    return 'RZP-'+hashlib.sha256(raw.encode()).hexdigest()[:12].upper()


def payment_to_payload(payment, now_iso):
    amount=float(payment.get('amount',0))/100.0
    customer_id=pseudonymous_customer(payment)
    base=customer_features(customer_id,amount,now_iso)
    method=str(payment.get('method') or 'upi').lower()
    return {'customer_id':customer_id,'amount':amount,'payment_method':method,**base}


def verify_webhook(raw_body: bytes, signature: str|None):
    if not WEBHOOK_SECRET:
        raise HTTPException(503,'RAZORPAY_WEBHOOK_SECRET is not configured')
    if not signature:
        raise HTTPException(400,'Missing X-Razorpay-Signature')
    expected=hmac.new(WEBHOOK_SECRET.encode(),raw_body,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature):
        raise HTTPException(400,'Invalid Razorpay webhook signature')

async def broadcast(event):
    dead=[]
    for ws in list(clients):
        try: await ws.send_json(event)
        except Exception: dead.append(ws)
    for ws in dead: clients.discard(ws)

@app.post('/api/v1/demo/event')
async def demo_event(request: Request):
    if not DEMO_MODE:
        raise HTTPException(404, 'Demo event endpoint is disabled')
    if DEMO_EVENT_KEY and request.headers.get('X-Demo-Key') != DEMO_EVENT_KEY:
        raise HTTPException(401, 'Invalid demo key')
    now=datetime.now(timezone.utc).isoformat()
    customer_id='DEMO-'+uuid.uuid4().hex[:8].upper()
    amount=round(random.uniform(250, 18000), 2)
    method=random.choice(['upi','card','netbanking','wallet'])
    payload={'customer_id':customer_id,'amount':amount,'payment_method':method,**customer_features(customer_id,amount,now)}
    result=engine.score(payload)
    txid='DEMO-'+uuid.uuid4().hex[:10].upper()
    event_type='demo.transaction'
    save_transaction(txid,now,payload,result,label=None,source='demo',provider_id=txid,event_type=event_type,currency='INR')
    event={'transaction_id':txid,'created_at':now,'source':'demo','event_type':event_type,'provider_id':txid,'currency':'INR',**payload,**result}
    await broadcast(event)
    return {'ok':True,**event}

@app.post('/api/v1/webhooks/razorpay')
async def razorpay_webhook(request: Request):
    raw = await request.body()

    verify_webhook(
        raw,
        request.headers.get('X-Razorpay-Signature')
    )

    payload = json.loads(raw.decode('utf-8'))

    event_type = payload.get('event', '')

    payment = (
        (payload.get('payload') or {})
        .get('payment') or {}
    ).get('entity') or {}

    if not payment:
        return {
            'ok': True,
            'ignored': True,
            'event': event_type
        }

    supported = {
        'payment.authorized',
        'payment.captured',
        'payment.failed'
    }

    if event_type not in supported:
        return {
            'ok': True,
            'ignored': True,
            'event': event_type
        }

    provider_id = str(payment.get('id') or '')

    if not provider_id:
        raise HTTPException(
            400,
            'Webhook payment id missing'
        )

    now = datetime.now(timezone.utc).isoformat()

    # -------------------------------------------------
    # DEDUPLICATE THE SAME RAZORPAY EVENT
    # -------------------------------------------------

    c = db()

    claimed = c.execute(
        """
        INSERT OR IGNORE INTO webhook_events
        (
            provider_id,
            event_type,
            received_at
        )
        VALUES(?,?,?)
        """,
        (
            provider_id,
            event_type,
            now
        )
    ).rowcount

    c.commit()
    c.close()

    if not claimed:
        c = db()

        existing = c.execute(
            'SELECT id FROM transactions WHERE provider_id=?',
            (provider_id,)
        ).fetchone()

        c.close()

        return {
            'ok': True,
            'duplicate': True,
            'transaction_id':
                existing['id']
                if existing
                else 'RZP-' + provider_id
        }

    # -------------------------------------------------
    # CONVERT RAZORPAY PAYMENT TO OUR TRANSACTION
    # -------------------------------------------------

    tx = payment_to_payload(
        payment,
        now
    )

    result = engine.score(tx)

    txid = 'RZP-' + provider_id

    txid, created = save_transaction(
        txid,
        now,
        tx,
        result,
        label=None,
        source='razorpay',
        provider_id=provider_id,
        event_type=event_type,
        currency=payment.get(
            'currency',
            'INR'
        )
    )

    # -------------------------------------------------
    # HUMAN-READABLE PAYMENT STATUS
    # -------------------------------------------------

    if event_type == 'payment.failed':
        payment_status = 'FAILED'

    elif event_type == 'payment.captured':
        payment_status = 'CAPTURED'

    elif event_type == 'payment.authorized':
        payment_status = 'AUTHORIZED'

    else:
        payment_status = 'UNKNOWN'

    # -------------------------------------------------
    # SEND TO LIVE DASHBOARD
    # -------------------------------------------------

    event = {
        'transaction_id': txid,
        'created_at': now,

        'source': 'razorpay',
        'event_type': event_type,
        'provider_id': provider_id,

        'payment_status': payment_status,

        'currency': payment.get(
            'currency',
            'INR'
        ),

        **tx,
        **result,

        'type':
            'transaction_created'
            if created
            else 'transaction_updated'
    }

    await broadcast(event)

    return {
        'ok': True,
        'transaction_id': txid,
        'created': created,

        'payment_status': payment_status,

        'risk_score': result['risk_score'],
        'risk_level': result['risk_level'],
        'decision': result['decision']
    }
@app.post('/api/v1/transactions/{txid}/action')
async def action(txid:str, req:ActionRequest):
    allowed={'ALLOW','VERIFY','MANUAL REVIEW','RESOLVE','DISMISS'}
    if req.action.upper() not in allowed: raise HTTPException(400,'Unsupported workflow action')
    c=db(); r=c.execute('SELECT id FROM transactions WHERE id=?',(txid,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Transaction not found')
    status='closed' if req.action.upper() in {'RESOLVE','DISMISS','ALLOW'} else 'open'
    now=datetime.now(timezone.utc).isoformat(); c.execute('UPDATE transactions SET status=? WHERE id=?',(status,txid)); c.execute('INSERT INTO audit_logs(transaction_id,created_at,action,actor) VALUES(?,?,?,?)',(txid,now,req.action.upper(),'operator')); c.commit(); c.close(); return {'ok':True,'transaction_id':txid,'action':req.action.upper(),'status':status}

@app.post('/api/v1/simulator/reset')
def reset():
    c=db(); c.execute("DELETE FROM transactions WHERE source IN ('simulation','demo')"); c.execute("DELETE FROM audit_logs WHERE actor IN ('simulation','demo')"); c.commit(); c.close(); return {'ok':True}

@app.websocket('/ws/transactions')
async def websocket(ws:WebSocket):
    await ws.accept(); clients.add(ws)
    try:
        # WebSocket is now a real-time fan-out channel. It does not fabricate data.
        await ws.send_json({'type':'status','source':'razorpay','message':'Connected. Waiting for Razorpay webhook events.'})
        while True:
            msg=await ws.receive_json()
            if msg.get('command')=='ping': await ws.send_json({'type':'pong'})
            elif msg.get('command')=='start': await ws.send_json({'type':'status','source':'razorpay','message':'Live ingestion is enabled; waiting for webhook events.'})
            elif msg.get('command')=='pause': await ws.send_json({'type':'status','source':'razorpay','message':'Pause only affects the demo simulator.'})
    except WebSocketDisconnect: pass
    finally: clients.discard(ws)
