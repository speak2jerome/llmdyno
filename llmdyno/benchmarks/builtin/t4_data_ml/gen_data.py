"""Generate the messy raw data for t4 plus the hidden ground truth used by the grader.

Run inside the sandbox image:  python gen_data.py <task_dir>
Writes <task_dir>/workspace/data/* and <task_dir>/grader/{truth.json,test_labels.csv,truth_features.parquet}.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

rng = np.random.default_rng(20261025)
TASK = Path(sys.argv[1])
DATA = TASK / "workspace" / "data"
GRADER = TASK / "grader"
DATA.mkdir(parents=True, exist_ok=True)

END = date(2026, 6, 30)
EVENT_START = date(2024, 7, 1)
N = 4000
COUNTRIES = ["US", "GB", "DE", "IN", "FR", "BR", "JP", "CA"]
C_WEIGHTS = np.array([30, 12, 10, 14, 8, 9, 7, 10], float)
VARIANTS = {
    "US": ["US", "us", "USA", "usa", "United States", " united states ", "U.S."],
    "GB": ["GB", "gb", "UK", "uk", "GBR", "United Kingdom", "united kingdom "],
    "DE": ["DE", "de", "DEU", "Germany", " germany"],
    "IN": ["IN", "in", "IND", "India", "india "],
    "FR": ["FR", "fr", "FRA", "France"],
    "BR": ["BR", "BRA", "Brazil", "brazil"],
    "JP": ["JP", "jp", "JPN", "Japan"],
    "CA": ["CA", "CAN", "Canada", " canada"],
}
PLANS = ["basic", "pro", "enterprise"]
PLAN_W = [0.5, 0.35, 0.15]
PLAN_NOISE = {"basic": ["basic", "Basic", " basic", "BASIC "], "pro": ["pro", "Pro", "PRO", " pro "],
              "enterprise": ["enterprise", "Enterprise", "ENTERPRISE", "enterprise "]}
PLAN_EFF = {"basic": 0.6, "pro": 0.0, "enterprise": -0.9}


def fmt_date(d):
    r = rng.random()
    if r < 0.7:
        return d.isoformat()
    if r < 0.9:
        return d.strftime("%Y/%m/%d")
    return f"{d.isoformat()}T{rng.integers(0, 24):02d}:{rng.integers(0, 60):02d}:00"


customers = []
truth_rows = []
events = []
for i in range(1, N + 1):
    cid = f"C{i:05d}"
    country = rng.choice(COUNTRIES, p=C_WEIGHTS / C_WEIGHTS.sum())
    plan = rng.choice(PLANS, p=PLAN_W)
    signup = date(2024, 1, 1) + timedelta(days=int(rng.integers(0, 820)))
    r = rng.random()
    if r < 0.06:
        age_raw, age_valid = "", None
    elif r < 0.08:
        age_raw, age_valid = str(rng.choice([-1, 0, 150, 999, 12])), None
    else:
        a = int(np.clip(rng.normal(38, 11), 18, 80))
        age_raw, age_valid = str(a), a
    e = rng.normal()
    logit = -1.1 - 1.1 * e + PLAN_EFF[plan] + rng.normal(0, 0.5)
    churned = int(rng.random() < 1 / (1 + np.exp(-logit)))
    start = max(signup, EVENT_START)
    if churned:
        end_active = END - timedelta(days=int(rng.integers(10, 250)))
    else:
        end_active = END - timedelta(days=int(rng.integers(0, 60)))
    end_active = max(end_active, start + timedelta(days=7))
    end_active = min(end_active, END)
    active_days = max((end_active - start).days, 1)
    lam = 0.06 * np.exp(0.7 * e)
    n_act = rng.poisson(lam * active_days)
    n_purch = rng.poisson(0.15 * lam * active_days)
    n_tick = rng.poisson((0.03 if churned else 0.01) * active_days / 7)
    for kind, n in (("activity", n_act), ("purchase", n_purch), ("support_ticket", n_tick)):
        for _ in range(n):
            day = start + timedelta(days=int(rng.integers(0, active_days + 1)))
            ts = datetime(day.year, day.month, day.day, int(rng.integers(0, 24)), int(rng.integers(0, 60)),
                          int(rng.integers(0, 60)), tzinfo=timezone.utc)
            et = rng.choice(["login", "page_view"], p=[0.4, 0.6]) if kind == "activity" else kind
            amount = None
            if et == "purchase":
                amount = round(float(rng.lognormal(3.0, 0.6)) * (1.6 if plan == "enterprise" else 1.0), 2)
            events.append({"customer_id": cid, "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "event_type": et,
                           "amount": amount})
    if rng.random() < 0.08:  # label noise: outcome not fully explained by behaviour
        churned = 1 - churned
    row = {"customer_id": cid, "signup_date": fmt_date(signup), "country": rng.choice(VARIANTS[country]),
           "age": age_raw, "plan": rng.choice(PLAN_NOISE[plan])}
    customers.append(row)
    truth_rows.append({"customer_id": cid, "signup_date": signup, "country": country, "plan": plan,
                       "age_valid": age_valid, "churned": churned})

# Duplicate customer rows: an older stale record that must lose to the latest signup_date.
dup_ids = rng.choice(N, size=150, replace=False)
for idx in dup_ids:
    t = truth_rows[idx]
    older = t["signup_date"] - timedelta(days=int(rng.integers(30, 400)))
    stale_country = rng.choice(COUNTRIES)
    customers.append({"customer_id": t["customer_id"], "signup_date": fmt_date(older),
                      "country": rng.choice(VARIANTS[stale_country]), "age": str(int(rng.integers(18, 80))),
                      "plan": rng.choice(PLAN_NOISE[rng.choice(PLANS)])})
order = rng.permutation(len(customers))
pd.DataFrame([customers[i] for i in order]).to_csv(DATA / "customers.csv", index=False)

# Event noise: string amounts, exact duplicates, orphans.
clean_events = list(events)
raw_events = []
for ev in events:
    out = dict(ev)
    if out["amount"] is not None and rng.random() < 0.15:
        out["amount"] = f"{out['amount']:.2f}"
    raw_events.append(out)
n_dups = int(len(raw_events) * 0.015)
for j in rng.choice(len(raw_events), size=n_dups, replace=False):
    raw_events.append(dict(raw_events[j]))
for _ in range(int(len(events) * 0.01)):
    raw_events.append({"customer_id": f"C9{rng.integers(0, 9999):04d}", "ts": "2026-02-01T10:00:00Z",
                       "event_type": "purchase", "amount": 42.0})
raw_events = [raw_events[i] for i in rng.permutation(len(raw_events))]
with open(DATA / "events.jsonl", "w") as f:
    for ev in raw_events:
        f.write(json.dumps(ev) + "\n")

# ---- Ground truth, computed from the clean generative records ----
ev = pd.DataFrame(clean_events)
ev["amount"] = ev["amount"].astype(float)
# exact duplicates among the clean generated events are possible by chance; dedup like the rules say
ev = ev.drop_duplicates(subset=["customer_id", "ts", "event_type", "amount"])
ev["date"] = pd.to_datetime(ev["ts"], utc=True).dt.date
truth = pd.DataFrame(truth_rows)
valid_ages = truth["age_valid"].dropna()
median_age = float(valid_ages.median())
truth["age"] = truth["age_valid"].fillna(median_age)
g = ev.groupby("customer_id")
feat = pd.DataFrame({
    "n_events": g.size(),
    "n_purchases": g.apply(lambda d: int((d.event_type == "purchase").sum())),
    "total_amount": g.apply(lambda d: float(d.loc[d.event_type == "purchase", "amount"].sum())),
    "n_support_tickets": g.apply(lambda d: int((d.event_type == "support_ticket").sum())),
    "last_date": g["date"].max(),
})
truth = truth.merge(feat, left_on="customer_id", right_index=True, how="left")
for c in ("n_events", "n_purchases", "n_support_tickets"):
    truth[c] = truth[c].fillna(0).astype(int)
truth["total_amount"] = truth["total_amount"].fillna(0.0).round(2)
truth["days_since_last_event"] = [
    (END - (ld if isinstance(ld, date) else sd)).days for ld, sd in zip(truth["last_date"], truth["signup_date"])]

ids = truth["customer_id"].to_numpy()
perm = rng.permutation(len(ids))
n_train = int(len(ids) * 0.7)
train_ids, test_ids = set(ids[perm[:n_train]]), set(ids[perm[n_train:]])
train = truth[truth.customer_id.isin(train_ids)].sort_values("customer_id")
test = truth[truth.customer_id.isin(test_ids)].sort_values("customer_id")
train[["customer_id", "churned"]].to_csv(DATA / "labels_train.csv", index=False)
test[["customer_id"]].to_csv(DATA / "test_ids.csv", index=False)
GRADER.mkdir(exist_ok=True)
test[["customer_id", "churned"]].to_csv(GRADER / "test_labels.csv", index=False)

purch = ev[ev.event_type == "purchase"].merge(truth[["customer_id", "country"]], on="customer_id")
top3 = purch.groupby("country")["amount"].sum().sort_values(ascending=False).index[:3].tolist()
purch["month"] = pd.to_datetime(purch["ts"], utc=True).dt.strftime("%Y-%m")
rev = purch[purch.month.str.startswith("2026")].groupby("month")["amount"].sum().round(2).to_dict()

# Oracle-ish reference model to calibrate AUC thresholds.
X_cols = ["n_events", "n_purchases", "total_amount", "n_support_tickets", "days_since_last_event", "age"]
def X(df):
    out = df[X_cols].astype(float).copy()
    for p in PLANS:
        out[f"plan_{p}"] = (df["plan"] == p).astype(float)
    out["log_events"] = np.log1p(out["n_events"])
    out["log_days"] = np.log1p(out["days_since_last_event"])
    return out
clf = LogisticRegression(max_iter=2000).fit(X(train), train["churned"])
ref_auc = float(roc_auc_score(test["churned"], clf.predict_proba(X(test))[:, 1]))

out_truth = {
    "n_customers": int(len(truth)),
    "n_events_clean": int(len(ev)),
    "train_churn_rate": round(float(train["churned"].mean()), 4),
    "median_age": median_age,
    "top_countries_by_revenue": top3,
    "revenue_by_month_2026": {m: rev.get(m, 0.0) for m in [f"2026-{k:02d}" for k in range(1, 7)]},
    "reference_test_auc": round(ref_auc, 4),
    "n_raw_customer_rows": len(customers), "n_raw_events": len(raw_events),
}
(GRADER / "truth.json").write_text(json.dumps(out_truth, indent=2))
keep = ["customer_id", "country", "plan", "age", "n_events", "n_purchases", "total_amount", "n_support_tickets",
        "days_since_last_event", "churned"]
tf = truth[keep].copy()
tf["signup_date"] = truth["signup_date"].astype(str)
tf.to_parquet(GRADER / "truth_features.parquet", index=False)
print(json.dumps(out_truth, indent=2))
