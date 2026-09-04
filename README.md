# RiskShield AI

Defense-only, real-time merchant transaction risk manager for Razorpay Buildathon Track 02.

## What it demonstrates
- Synthetic transaction stream with customer behavioral baselines.
- Random Forest risk classifier with a Logistic Regression baseline.
- Chronological-style 80/20 hold-out evaluation; the final 20% is never used for training.
- Precision, recall, F1, ROC-AUC, PR-AUC, false-positive rate and confusion matrix.
- Explicit demo false-positive cost and illustrative estimated loss prevented.
- Explainable risk factors and operational decisions: ALLOW / VERIFY / MANUAL REVIEW.
- FastAPI REST APIs, SQLite persistence and WebSocket live updates.
- Functional dashboard tabs, search/filtering, alerts, transaction details, customer risk, analytics, audit workflow and simulation controls.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```
Open http://127.0.0.1:8000

## Docker
```bash
docker compose up --build
```

## Evaluation honesty
The metrics are computed at application startup from generated synthetic data. They are not Razorpay production metrics. The cost model is explicitly illustrative. If you replace the dataset, rerun the evaluation and use the resulting metrics in your pitch.

## Architecture
Browser dashboard → FastAPI → feature engineering → Random Forest → decision/explanation → SQLite → WebSocket broadcast.

## API
- `GET /api/v1/metrics`
- `GET /api/v1/model`
- `GET /api/v1/analytics`
- `GET /api/v1/transactions`
- `GET /api/v1/transactions/{id}`
- `GET /api/v1/alerts`
- `POST /api/v1/risk/score`
- `POST /api/v1/transactions/{id}/action`
- `POST /api/v1/simulator/reset`
- `WS /ws/transactions`

## Demo flow
1. Start the simulator.
2. Watch transactions stream into the dashboard without refresh.
3. Open a HIGH risk event and show the explanation.
4. Open Risk Alerts and Transaction Explorer.
5. Show Model Performance and the held-out metrics.
6. Show Analytics and Customer Risk.
7. Resolve an alert and demonstrate persistence.

All data is synthetic/demo data and the product is defense-only.
