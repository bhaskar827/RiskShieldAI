import sys
sys.path.insert(0, '.')
from app.risk_engine import RiskEngine

def test_metrics_exist():
    e=RiskEngine(); assert 0<=e.metrics['precision']<=1; assert 0<=e.metrics['recall']<=1; assert e.dataset_info['held_out_rows']>0

def test_score_decision():
    e=RiskEngine(); r=e.score({'amount':5000,'average_transaction_amount':500,'account_age_days':5,'transactions_last_1h':10,'failed_attempts_1h':3,'device_changes_24h':1,'location_changes_24h':1,'previous_chargebacks':1,'previous_refunds':0,'payment_method':'upi','customer_transaction_frequency':8,'time_since_previous_transaction_min':2})
    assert r['risk_level'] in {'LOW','MEDIUM','HIGH'}; assert r['decision'] in {'ALLOW','VERIFY','MANUAL REVIEW'}
