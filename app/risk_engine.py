from pathlib import Path
import numpy as np, pandas as pd, random, math, joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, average_precision_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FEATURE_NAMES=['amount','account_age_days','transactions_last_1h','failed_attempts_1h','amount_deviation_ratio','device_changes_24h','location_changes_24h','previous_chargebacks','previous_refunds','payment_method_code','customer_transaction_frequency','time_since_previous_transaction_min']
PAYMENT={'upi':0,'card':1,'netbanking':2,'wallet':3}
ROOT=Path(__file__).resolve().parent.parent
MODEL_PATH=ROOT/'data'/'risk_model.joblib'

class RiskEngine:
    def __init__(self):
        self.model_version='riskshield-rf-1.0'
        self.thresholds={'medium':45,'high':70}
        self.model, self.metrics, self.dataset_info=self._train()
    def _dataset(self,n=18000,seed=42):
        rng=np.random.default_rng(seed); rows=[]
        for i in range(n):
            age=int(rng.integers(5,1500)); avg=float(np.exp(rng.normal(7.0,.65))); amount=float(max(50,np.exp(rng.normal(math.log(avg),.8))))
            t1=int(rng.poisson(2.2)); failed=int(rng.poisson(.25)); dc=int(rng.binomial(2,.07)); lc=int(rng.binomial(2,.05)); cb=int(rng.binomial(2,.025)); ref=int(rng.poisson(.4)); freq=float(rng.gamma(2,1.5)); gap=float(max(2,rng.exponential(180))); pm=int(rng.integers(0,4))
            dev=abs(amount-avg)/max(avg,1)
            logit=-4.1 + 1.0*dev + .55*t1 + .9*failed + .9*dc + .8*lc + 1.5*cb + .18*ref + .08*freq + (.7 if gap<15 else 0) + (.7 if age<30 else 0) + (.35 if pm==3 else 0)
            p=1/(1+math.exp(-logit)); y=int(rng.random()<p)
            rows.append([amount,age,t1,failed,dev,dc,lc,cb,ref,pm,freq,gap,y])
        return pd.DataFrame(rows,columns=FEATURE_NAMES+['label'])
    def _train(self):
        df=self._dataset(); X=df[FEATURE_NAMES]; y=df.label
        # Chronological-style holdout surrogate: generation order is preserved, last 20% held out.
        cut=int(len(df)*.8); Xtr,Xte=X.iloc[:cut],X.iloc[cut:]; ytr,yte=y.iloc[:cut],y.iloc[cut:]
        lr=Pipeline([('scale',StandardScaler()),('model',LogisticRegression(max_iter=1000,class_weight='balanced'))]); lr.fit(Xtr,ytr)
        rf=RandomForestClassifier(n_estimators=220,max_depth=10,min_samples_leaf=5,class_weight='balanced_subsample',random_state=42,n_jobs=-1); rf.fit(Xtr,ytr)
        probs=rf.predict_proba(Xte)[:,1]; pred=(probs>=.5).astype(int)
        tn,fp,fn,tp=confusion_matrix(yte,pred).ravel(); fp_cost=float(fp*120); prevented=float(tp*900)
        m={'accuracy':round(accuracy_score(yte,pred),4),'precision':round(precision_score(yte,pred,zero_division=0),4),'recall':round(recall_score(yte,pred,zero_division=0),4),'f1':round(f1_score(yte,pred,zero_division=0),4),'roc_auc':round(roc_auc_score(yte,probs),4),'pr_auc':round(average_precision_score(yte,probs),4),'false_positive_rate':round(fp/max(fp+tn,1),4),'false_positive_cost_demo':round(fp_cost,2),'estimated_loss_prevented_demo':round(prevented,2),'confusion_matrix':{'tn':int(tn),'fp':int(fp),'fn':int(fn),'tp':int(tp)}}
        self.baseline={'model':'Logistic Regression','roc_auc':round(roc_auc_score(yte,lr.predict_proba(Xte)[:,1]),4)}
        return rf,m,{'rows':len(df),'train_rows':cut,'held_out_rows':len(df)-cut,'fraud_rate':round(float(y.mean()),4),'note':'Synthetic demo data; last 20% held out and never used for training.'}
    def vector(self,p):
        avg=max(float(p.get('average_transaction_amount',900)),1); amount=float(p.get('amount',1000)); dev=abs(amount-avg)/avg
        return np.array([[amount,p.get('account_age_days',180),p.get('transactions_last_1h',2),p.get('failed_attempts_1h',0),dev,p.get('device_changes_24h',0),p.get('location_changes_24h',0),p.get('previous_chargebacks',0),p.get('previous_refunds',0),PAYMENT.get(p.get('payment_method','upi'),0),p.get('customer_transaction_frequency',2),p.get('time_since_previous_transaction_min',180)]])
    def score(self,p):
        prob=float(self.model.predict_proba(self.vector(p))[0,1]); score=round(prob*100,1)
        level='HIGH' if score>=70 else ('MEDIUM' if score>=45 else 'LOW'); decision='MANUAL REVIEW' if level=='HIGH' else ('VERIFY' if level=='MEDIUM' else 'ALLOW')
        avg=max(float(p.get('average_transaction_amount',900)),1); dev=abs(float(p.get('amount',1000))-avg)/avg; factors=[]
        checks=[(dev>=1.0,'Amount is unusually far from the customer baseline',min(30,dev*15)),(p.get('failed_attempts_1h',0)>=2,'Multiple failed attempts recently',12),(p.get('transactions_last_1h',0)>=7,'High transaction velocity',12),(p.get('device_changes_24h',0)>=1,'Recent device change',10),(p.get('location_changes_24h',0)>=1,'Recent location change',9),(p.get('previous_chargebacks',0)>=1,'Prior chargeback history',14),(p.get('account_age_days',180)<30,'New account',10),(p.get('time_since_previous_transaction_min',180)<10,'Very short time since previous transaction',8)]
        for ok,text,w in checks:
            if ok: factors.append({'factor':text,'weight':round(w,1)})
        return {'risk_score':score,'risk_probability':round(prob,4),'risk_level':level,'decision':decision,'confidence':round(abs(prob-.5)*2,3),'factors':factors[:5],'model_version':self.model_version}
    def generate_transaction(self):
        rng=np.random.default_rng(); age=int(rng.integers(7,1200)); avg=float(np.exp(rng.normal(7,.7))); amount=float(max(80,np.exp(rng.normal(math.log(avg),.75))))
        anomaly=rng.random()<.13
        return {'customer_id':f'CUS-{int(rng.integers(1000,9999))}','amount':round(amount*(rng.uniform(2,5) if anomaly else 1),2),'account_age_days':age,'transactions_last_1h':int(rng.poisson(8 if anomaly else 2)),'failed_attempts_1h':int(rng.poisson(2 if anomaly else .15)),'average_transaction_amount':round(avg,2),'device_changes_24h':int(rng.binomial(2,.4 if anomaly else .05)),'location_changes_24h':int(rng.binomial(2,.35 if anomaly else .04)),'previous_chargebacks':int(rng.binomial(2,.25 if anomaly else .02)),'previous_refunds':int(rng.poisson(1 if anomaly else .3)),'payment_method':random.choice(list(PAYMENT)),'customer_transaction_frequency':round(float(rng.gamma(2,2)),2),'time_since_previous_transaction_min':round(float(max(1,rng.exponential(15 if anomaly else 180))),2)}
