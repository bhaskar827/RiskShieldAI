const state={tab:'overview',ws:null,running:false,tx:[],metrics:null,mode:'server_live',reconnectTimer:null,reconnectDelay:1000};
const nav=[['overview','Risk Dashboard'],['live','Live Transactions'],['alerts','Risk Alerts'],['explorer','Transaction Explorer'],['model','Model Performance'],['analytics','Risk Analytics'],['customers','Customer Risk'],['audit','Audit Logs'],['settings','Settings']];
function el(id){return document.getElementById(id)}
function api(path,opt){return fetch(path,opt).then(r=>r.json())}
function shell(){el('app').innerHTML=`<div class="shell"><aside class="side"><div class="brand"><b>RISKSHIELD AI</b><span>MERCHANT RISK MANAGER</span></div><div class="status">● SYSTEM ONLINE <span class="pill">RAZORPAY TEST MODE</span></div><div class="navlabel">OPERATIONS</div><div class="nav">${nav.slice(0,7).map(n=>`<button data-tab="${n[0]}">${n[1]} ${n[0]=='alerts'?'<span id="alertCount"></span>':''}</button>`).join('')}<div class="navlabel">SYSTEM</div>${nav.slice(7).map(n=>`<button data-tab="${n[0]}">${n[1]}</button>`).join('')}</div><div class="footer">Razorpay Test Mode + Demo Simulation • v1.1.0<br>Defense-only risk scoring</div></aside><main class="main"><div class="top"><div class="title"><h1 id="pageTitle">Risk Dashboard</h1><p>Real-time transaction risk intelligence</p></div><div class="actions"><button class="btn" id="testBtn">Send Demo Event</button><button class="btn primary" id="runBtn">Connect Live Feed</button></div></div>${nav.map(n=>`<section id="tab-${n[0]}" class="tab"></section>`).join('')}</main></div><div class="modal" id="modal"><div class="modalbox" id="modalbox"></div></div>`;document.querySelectorAll('.nav button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));el('runBtn').onclick=toggleRun;el('testBtn').onclick=sendTestEvent;setTab('overview');loadAll();connect()}
async function loadAll(){state.metrics=await api('/api/v1/metrics');renderOverview();renderModel();renderAnalytics();renderExplorer();renderAlerts();renderCustomers();renderAudit();renderSettings();refreshHeader()}
function setTab(t){state.tab=t;nav.forEach(n=>document.querySelector(`[data-tab="${n[0]}"]`)?.classList.toggle('active',n[0]===t));document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));el('tab-'+t).classList.add('active');el('pageTitle').textContent=nav.find(n=>n[0]===t)[1];if(t==='live')renderLive();if(t==='audit')renderAudit();}
function refreshHeader(){api('/api/v1/alerts').then(a=>{el('alertCount').textContent=a.length?' '+a.length:''})}
async function renderOverview(){const a=await api('/api/v1/analytics');el('tab-overview').innerHTML=`<div class="grid"><div class="card metric"><div class="label">TRANSACTIONS</div><div class="value">${a.total_transactions.toLocaleString()}</div><div class="sub">persisted events</div></div><div class="card metric"><div class="label">HIGH RISK</div><div class="value high">${a.high_risk}</div><div class="sub">requires review</div></div><div class="card metric"><div class="label">VOLUME</div><div class="value">₹${Math.round(a.volume).toLocaleString()}</div><div class="sub">Razorpay Test Mode volume</div></div><div class="card metric"><div class="label">EST. EXPOSURE</div><div class="value medium">₹${Math.round(a.estimated_exposure).toLocaleString()}</div><div class="sub">non-allow decisions</div></div></div><div class="layout"><div class="card"><h2>LIVE RISK FEED <span class="pill">● REAL-TIME</span></h2><div id="feed" class="feed"></div></div><div class="card"><h2>MODEL SIGNAL</h2><div class="metric"><div class="label">PRECISION</div><div class="value">${(state.metrics.precision*100).toFixed(1)}%</div></div><div class="metric" style="margin-top:22px"><div class="label">RECALL</div><div class="value">${(state.metrics.recall*100).toFixed(1)}%</div></div><div class="metric" style="margin-top:22px"><div class="label">F1 SCORE</div><div class="value">${(state.metrics.f1*100).toFixed(1)}%</div></div></div></div><div class="footer">Metrics are computed from a held-out synthetic test set. Demo cost estimates are illustrative, not Razorpay financial figures.</div>`;renderFeed()}
function renderLive(){const x=el('tab-live'); if(!x)return; x.innerHTML=`<div class="card"><h2>LIVE TRANSACTIONS <span class="pill">● RAZORPAY WEBHOOK STREAM</span></h2><div class="small">Events are scored when Razorpay sends them to the webhook. No synthetic transactions are generated in live mode.</div><div id="liveFeed" class="feed"></div></div>`; const f=el('liveFeed'); if(f) f.innerHTML=state.tx.slice(0,50).map(t=>`<div class="row" onclick="showTx('${t.transaction_id}')"><div><b>${t.transaction_id}</b>
<div class="mono">
    Razorpay: ${t.provider_id||'N/A'}
</div> <div class="small">
    ${t.payment_method?.toUpperCase()||'PAYMENT'}
    • ${t.customer_id}
    • <b>${t.source?.toUpperCase()||'UNKNOWN'}</b>
</div>
</div><div><span class="badge ${t.risk_level.toLowerCase()}">${t.risk_score} ${t.risk_level}</span><div class="small">
    ${t.decision} • ${t.payment_status || t.status || 'UNKNOWN'}
</div></div></div>`).join('')||'<div class="small">Waiting for stream…</div>'}
function renderFeed(){const f=el('feed');if(!f)return;f.innerHTML=state.tx.slice(0,25).map(t=>`<div class="row" onclick="showTx('${t.transaction_id}')"><div><b>${t.payment_method?.toUpperCase()||'PAYMENT'} • ₹${Number(t.amount).toFixed(0)}</b><div class="mono">${t.transaction_id}</div><div class="small">${t.customer_id} • ${new Date(t.created_at).toLocaleTimeString()}</div></div><div><span class="badge ${t.risk_level.toLowerCase()}">${t.risk_level}</span><div class="small">
    ${t.decision} • ${t.payment_status || t.status || 'UNKNOWN'}
</div></div></div>`).join('')||'<div class="small">Connect the live feed, then make a Razorpay test-mode payment to see it here.</div>'}
function toggleRun(){connect()}
async function sendTestEvent(){const btn=el('testBtn');btn.disabled=true;try{const r=await fetch('/api/v1/demo/event',{method:'POST'});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Demo event disabled');}catch(e){alert(e.message)}finally{btn.disabled=false}}
function connect(){
    if(state.ws && state.ws.readyState===1){
        state.running=true;
        return;
    }

    if(state.reconnectTimer){
        clearTimeout(state.reconnectTimer);
        state.reconnectTimer=null;
    }

    state.ws=new WebSocket(
        (location.protocol==='https:'?'wss':'ws')+
        '://'+location.host+'/ws/transactions'
    );

    state.ws.onopen=()=>{
        state.running=true;
        state.reconnectDelay=1000;
        el('runBtn').textContent='● LIVE CONNECTED';
        el('runBtn').disabled=true;
    };

    state.ws.onmessage=e=>{
    const t=JSON.parse(e.data);

    if(t.type==='status'){
        return;
    }

    const i=state.tx.findIndex(
        x=>x.transaction_id===t.transaction_id
    );

    if(i>=0){
        state.tx[i]={
            ...state.tx[i],
            ...t
        };
    }else{
        state.tx.unshift(t);
    }

    state.tx=state.tx.slice(0,100);

    renderFeed();

    if(state.tab==='live'){
        renderLive();
    }

    renderOverview();
    renderAlerts();
    renderExplorer();
    renderCustomers();
    renderAudit();
    refreshHeader();
};
    state.ws.onerror=()=>{
        try{
            state.ws.close();
        }catch(e){}
    };

    state.ws.onclose=()=>{
        state.running=false;
        el('runBtn').disabled=false;
        el('runBtn').textContent='Connect Live Feed';

        state.reconnectTimer=setTimeout(
            connect,
            state.reconnectDelay
        );

        state.reconnectDelay=Math.min(
            state.reconnectDelay*2,
            10000
        );
    };
}
async function renderAlerts(){const a=await api('/api/v1/alerts');el('tab-alerts').innerHTML=`<div class="card"><h2>OPEN RISK ALERTS</h2>${a.length?a.map(t=>`<div class="row" onclick="showTx('${t.id}')"><div><b>${t.id} • ₹${t.amount.toFixed(0)}</b><div class="small">${t.customer_id} • ${new Date(t.created_at).toLocaleString()}</div></div><span class="badge high">HIGH ${t.risk_score}</span></div>`).join(''):'<div class="small">No open high-risk alerts.</div>'}</div>`}
async function renderExplorer(){el('tab-explorer').innerHTML=`<div class="card"><div class="toolbar"><input class="input" id="search" placeholder="Search transaction, customer, method"><select class="input" id="risk"><option value="">All risk</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select><button class="btn" onclick="searchTx()">Search</button></div><div id="table"></div></div>`;searchTx()}
async function searchTx(){const q=encodeURIComponent(el('search')?.value||'');const r=el('risk')?.value||'';const rows=await api(`/api/v1/transactions?limit=100&q=${q}&risk=${r}`);el('table').innerHTML=`<table class="table"><tr><th>Transaction</th><th>Amount</th><th>Risk</th><th>Decision</th><th>Time</th></tr>${rows.map(t=>`<tr onclick="showTx('${t.id}')"><td>${t.id}<div class="small">${t.customer_id}</div></td><td>₹${t.amount.toFixed(2)}</td><td class="${t.risk_level.toLowerCase()}">${t.risk_level} ${t.risk_score}</td><td>
    ${t.decision}
    <div class="small">
        ${t.payment_status || t.status || 'UNKNOWN'}
    </div>
</td><td>${new Date(t.created_at).toLocaleTimeString()}</td></tr>`).join('')}</table>`}
function renderModel(){const m=state.metrics;el('tab-model').innerHTML=`<div class="grid"><div class="card metric"><div class="label">PRECISION</div><div class="value">${(m.precision*100).toFixed(1)}%</div></div><div class="card metric"><div class="label">RECALL</div><div class="value">${(m.recall*100).toFixed(1)}%</div></div><div class="card metric"><div class="label">ROC-AUC</div><div class="value">${m.roc_auc.toFixed(3)}</div></div><div class="card metric"><div class="label">PR-AUC</div><div class="value">${m.pr_auc.toFixed(3)}</div></div></div><div class="layout"><div class="card"><h2>HELD-OUT TEST SET</h2><p class="small">${state.metrics.confusion_matrix.tn} true negatives · ${state.metrics.confusion_matrix.fp} false positives · ${state.metrics.confusion_matrix.fn} false negatives · ${state.metrics.confusion_matrix.tp} true positives</p><div class="factor">Accuracy: ${(m.accuracy*100).toFixed(1)}%</div><div class="factor">F1: ${(m.f1*100).toFixed(1)}%</div><div class="factor">False-positive rate: ${(m.false_positive_rate*100).toFixed(2)}%</div></div><div class="card"><h2>DEMO COST ANALYSIS</h2><div class="metric"><div class="label">FALSE POSITIVE COST</div><div class="value">₹${m.false_positive_cost_demo.toLocaleString()}</div></div><div class="small">Illustrative cost assumption: ₹120 per false positive.</div><div class="metric" style="margin-top:20px"><div class="label">EST. LOSS PREVENTED</div><div class="value">₹${m.estimated_loss_prevented_demo.toLocaleString()}</div></div></div></div>`}
function renderAnalytics(){el('tab-analytics').innerHTML=`<div class="layout"><div class="card"><h2>RISK DISTRIBUTION</h2><div id="bars" class="bars"></div></div><div class="card"><h2>THRESHOLDS</h2><div class="factor">LOW: &lt; 45</div><div class="factor">MEDIUM: 45–69.9</div><div class="factor">HIGH: ≥ 70</div><div class="small">Thresholds map probability to operational decisions: ALLOW, VERIFY, MANUAL REVIEW.</div></div></div>`;updateBars()}
async function updateBars(){const a=await api('/api/v1/analytics');const vals=[a.low_risk,a.medium_risk,a.high_risk];el('bars').innerHTML=vals.map((v,i)=>`<div style="flex:1;text-align:center"><div class="bar" style="height:${Math.max(5,v/(Math.max(...vals,1))*140)}px"></div><div class="small">${['LOW','MEDIUM','HIGH'][i]} ${v}</div></div>`).join('')}
function renderCustomers(){el('tab-customers').innerHTML=`<div class="card"><h2>CUSTOMER RISK VIEW</h2><div class="small">Customer-level behavior is used as a baseline; this demo view is derived from persisted transactions.</div><div id="cust"></div></div>`;api('/api/v1/transactions?limit=100').then(rows=>{const map={};rows.forEach(t=>{map[t.customer_id]??={n:0,hi:0,vol:0};map[t.customer_id].n++;map[t.customer_id].hi+=t.risk_level==='HIGH';map[t.customer_id].vol+=t.amount});el('cust').innerHTML=Object.entries(map).slice(0,25).map(([id,x])=>`<div class="row"><div><b>${id}</b><div class="small">${x.n} transactions</div></div><div><span class="badge ${x.hi?'high':'low'}">${x.hi?'WATCH':'NORMAL'}</span><div class="small">₹${Math.round(x.vol).toLocaleString()}</div></div></div>`).join('')})}
async function renderAudit(){const rows=await api('/api/v1/audit?limit=100');el('tab-audit').innerHTML=`<div class="card"><h2>AUDIT LOG</h2><div class="small">Every score and operator workflow action is persisted in SQLite.</div><table class="table"><tr><th>Time</th><th>Transaction</th><th>Action</th><th>Actor</th></tr>${rows.map(r=>`<tr><td>${new Date(r.created_at).toLocaleString()}</td><td>${r.transaction_id}</td><td>${r.action}</td><td>${r.actor}</td></tr>`).join('')}</table></div>`}
function renderSettings(){el('tab-settings').innerHTML=`<div class="card"><h2>LIVE INGESTION</h2><div class="factor">Source: Razorpay Webhooks</div><div class="factor">Events: payment.authorized, payment.captured, payment.failed</div><div class="factor">WebSocket: /ws/transactions</div><div class="factor">Signature: X-Razorpay-Signature (HMAC-SHA256)</div><div class="factor">Database: Server-side SQLite (PostgreSQL-ready)</div><div class="factor">Demo endpoint: /api/v1/demo/event</div><div class="small">
    The dashboard is server-driven.
    Razorpay Test Mode payment events are received through
    /api/v1/webhooks/razorpay, verified using HMAC-SHA256,
    scored by the risk engine, persisted, and streamed to the UI.
    The Demo Event button is an explicitly labelled demo-only path.
</div><button class="btn" onclick="resetDemo()">Clear Demo Events</button></div>`}
async function resetDemo(){await api('/api/v1/simulator/reset',{method:'POST'});state.tx=[];loadAll()}
async function showTx(id){const t=await api('/api/v1/transactions/'+id);el('modal').classList.add('open');el('modalbox').innerHTML=`<div style="display:flex;justify-content:space-between"><h2>${t.id}</h2><button class="btn" onclick="el('modal').classList.remove('open')">Close</button></div><div class="grid"><div class="factor">Risk<br><b class="${t.risk_level.toLowerCase()}">${t.risk_level} ${t.risk_score}</b></div><div class="factor">
    Decision<br>
    <b>${t.decision}</b>
</div>
<div class="factor">
    Payment Status<br>
    <b>${t.payment_status || t.status || 'UNKNOWN'}</b>
</div><div class="factor">Amount<br><b>₹${t.amount.toFixed(2)}</b></div><div class="factor">Customer<br><b>${t.customer_id}</b></div></div><h2>WHY THIS SCORE</h2>${t.factors.map(f=>`<div class="factor">${f.factor}<span style="float:right">+${f.weight}</span></div>`).join('')||'<div class="small">No dominant risk factors.</div>'}
<button class="btn" onclick="workflow('${id}','VERIFY')">Verify</button>
<button class="btn" onclick="workflow('${id}','ALLOW')">Allow</button>
<button class="btn" onclick="workflow('${id}','RESOLVE')">Resolve</button>
`;
}

async function workflow(id, action) {
    try {
        await api(
            `/api/v1/transactions/${encodeURIComponent(id)}/action`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    action: action
                })
            }
        );

        el('modal').classList.remove('open');
        await loadAll();

    } catch (error) {
        console.error('Workflow action failed:', error);
        alert('Action failed. Check the console.');
    }
}

shell();