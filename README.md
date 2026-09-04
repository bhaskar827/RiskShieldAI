# RiskShield AI

Defense-only, server-based, real-time merchant transaction risk manager for Razorpay Buildathon Track 02.

## What this version does

RiskShield is **event-driven**. The server is the source of truth:

```text
Payment event
   ↓
FastAPI server
   ↓
Risk Engine (Random Forest)
   ↓
Risk score + explanation + decision
   ↓
SQLite (server-side)
   ↓
WebSocket broadcast
   ↓
Dashboard updates instantly
```

It supports two event sources:

- **Razorpay webhook:** real payment events can be POSTed to `/api/v1/webhooks/razorpay`.
- **Server test event:** `/api/v1/demo/event` creates a clearly labelled demo event on the server so the full real-time pipeline can be tested without Razorpay credentials.

The demo event is not represented as a Razorpay payment.

## Local run

Use Python 3.12 for the pinned ML dependencies.

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
# source .venv/bin/activate
python -m pip install -r requirements.txt
set DEMO_MODE=true
python run.py
```

Open `http://127.0.0.1:8000`.

On the dashboard, click **Connect Live Feed**, then **Send Test Event**. The event is created by the server, scored by the ML model, stored, and broadcast over WebSocket.

## Deploy as a public server

The repository includes `render.yaml` for Render.

1. Put this project in a GitHub repository.
2. In Render, create a new Blueprint and connect the repository.
3. Render uses the included `render.yaml` to create the FastAPI web service.
4. The service must use the generated public `onrender.com` HTTPS URL.
5. Open that public URL and use **Connect Live Feed**.
6. Click **Send Test Event** to prove that the deployed server is processing events and pushing them to the browser.

The production start command is:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

WebSockets are supported by Render web services. Use `wss://` for public WebSocket connections; the frontend automatically selects `wss` when served over HTTPS.

### Important persistence note

This demo defaults to SQLite. On a cloud platform with an ephemeral filesystem, database contents can disappear when the service is replaced or redeployed. For a production deployment, connect the app to a managed PostgreSQL database or another persistent datastore.

## Razorpay integration later

You do **not** need Razorpay API keys for the server deployment or the server test-event flow.

When you are ready to connect Razorpay Test Mode, configure a public HTTPS webhook URL:

```text
POST https://YOUR-SERVER/api/v1/webhooks/razorpay
```

Set `RAZORPAY_WEBHOOK_SECRET` in the server environment. The implementation verifies the `X-Razorpay-Signature` HMAC using the raw webhook body and handles duplicate event IDs/provider events.

Supported payment events:

- `payment.authorized`
- `payment.captured`
- `payment.failed`

Do not put secrets in frontend code or commit them to Git.

## API

- `GET /api/v1/health`
- `GET /api/v1/metrics`
- `GET /api/v1/model`
- `GET /api/v1/analytics`
- `GET /api/v1/transactions`
- `GET /api/v1/transactions/{id}`
- `GET /api/v1/alerts`
- `GET /api/v1/audit`
- `POST /api/v1/risk/score`
- `POST /api/v1/demo/event`
- `POST /api/v1/webhooks/razorpay`
- `POST /api/v1/transactions/{id}/action`
- `POST /api/v1/simulator/reset`
- `WS /ws/transactions`

## ML evaluation

The model uses generated synthetic data and a chronological-style 80/20 held-out test set. Reported metrics are computed by the application and are not Razorpay production metrics. The false-positive cost and estimated loss prevented are illustrative demo calculations.

## Security / honesty

- Defense-only risk scoring.
- No offensive or exploitation functionality.
- Razorpay data is not fabricated.
- Demo events are explicitly labelled `source=demo`.
- Customer identifiers from webhook payloads are pseudonymized for the demo risk view.
- Webhook signatures are validated when a webhook secret is configured.
