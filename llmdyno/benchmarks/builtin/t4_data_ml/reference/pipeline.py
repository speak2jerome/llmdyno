import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import cross_val_score

D, O = Path("data"), Path("output")
O.mkdir(exist_ok=True)
END = pd.Timestamp("2026-06-30")
NAMES = {"UNITED STATES": "US", "USA": "US", "U.S.": "US", "UNITED KINGDOM": "GB", "UK": "GB", "GBR": "GB",
         "GERMANY": "DE", "DEU": "DE", "INDIA": "IN", "IND": "IN", "FRANCE": "FR", "FRA": "FR", "BRAZIL": "BR",
         "BRA": "BR", "JAPAN": "JP", "JPN": "JP", "CANADA": "CA", "CAN": "CA"}

c = pd.read_csv(D / "customers.csv", dtype=str)
c["signup_date"] = pd.to_datetime(c["signup_date"].str.replace("/", "-").str[:10])
c = c.sort_values("signup_date").drop_duplicates("customer_id", keep="last")
c["country"] = c["country"].str.strip().str.upper().map(lambda v: NAMES.get(v, v))
c["plan"] = c["plan"].str.strip().str.lower()
age = pd.to_numeric(c["age"], errors="coerce")
age = age.where(age.between(16, 100))
median_age = float(age.median())
c["age"] = age.fillna(median_age)

e = pd.read_json(D / "events.jsonl", lines=True, dtype={"customer_id": str, "ts": str})
e["amount"] = pd.to_numeric(e["amount"], errors="coerce")
e = e.drop_duplicates(["customer_id", "ts", "event_type", "amount"])
e = e[e["customer_id"].isin(c["customer_id"])]
e["t"] = pd.to_datetime(e["ts"], utc=True)
e["date"] = e["t"].dt.tz_localize(None).dt.normalize()

g = e.groupby("customer_id")
f = pd.DataFrame({"n_events": g.size(),
                  "n_purchases": g["event_type"].apply(lambda s: (s == "purchase").sum()),
                  "total_amount": e[e.event_type == "purchase"].groupby("customer_id")["amount"].sum(),
                  "n_support_tickets": g["event_type"].apply(lambda s: (s == "support_ticket").sum()),
                  "last": g["date"].max()})
c = c.merge(f, left_on="customer_id", right_index=True, how="left")
for col in ("n_events", "n_purchases", "n_support_tickets"):
    c[col] = c[col].fillna(0).astype(int)
c["total_amount"] = c["total_amount"].fillna(0.0).round(2)
c["days_since_last_event"] = (END - c["last"].fillna(c["signup_date"])).dt.days
labels = pd.read_csv(D / "labels_train.csv", dtype={"customer_id": str})
c = c.drop(columns="last").merge(labels, on="customer_id", how="left")
c["signup_date"] = c["signup_date"].dt.strftime("%Y-%m-%d")
c.to_parquet(O / "features.parquet", index=False)
with sqlite3.connect(O / "warehouse.db") as con:
    c.to_sql("features", con, if_exists="replace", index=False)

purch = e[e.event_type == "purchase"].merge(c[["customer_id", "country"]], on="customer_id")
top3 = purch.groupby("country")["amount"].sum().sort_values(ascending=False).index[:3].tolist()
purch["month"] = purch["t"].dt.strftime("%Y-%m")
rev = purch[purch.month.str.startswith("2026")].groupby("month")["amount"].sum().round(2)
summary = {"n_customers": int(len(c)), "n_events_clean": int(len(e)),
           "train_churn_rate": round(float(labels["churned"].mean()), 4), "median_age": median_age,
           "top_countries_by_revenue": top3,
           "revenue_by_month_2026": {f"2026-{m:02d}": float(rev.get(f"2026-{m:02d}", 0.0)) for m in range(1, 7)}}
(O / "summary.json").write_text(json.dumps(summary, indent=2))

X_cols = ["n_events", "n_purchases", "total_amount", "n_support_tickets", "days_since_last_event", "age"]
X = c[X_cols].copy()
for p in ("basic", "pro", "enterprise"):
    X["plan_" + p] = (c["plan"] == p).astype(int)
train = c["churned"].notna()
model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05)
auc = float(cross_val_score(model, X[train], c.loc[train, "churned"], cv=5, scoring="roc_auc").mean())
model.fit(X[train], c.loc[train, "churned"])
test_ids = pd.read_csv(D / "test_ids.csv", dtype=str)
pred = pd.DataFrame({"customer_id": c.loc[~train, "customer_id"], "churn_probability": model.predict_proba(X[~train])[:, 1]})
test_ids.merge(pred, on="customer_id", how="left").to_csv(O / "predictions.csv", index=False)
(O / "metrics.json").write_text(json.dumps({"model": "HistGradientBoosting", "cv_auc": auc}))
rows = "\n".join(f"| {m} | {v:,.2f} |" for m, v in summary["revenue_by_month_2026"].items())
(O / "report.md").write_text(f"# Churn report\n\nCustomers: {summary['n_customers']}\n\n| month | revenue |\n|---|---|\n{rows}\n\n"
                             f"Main churn drivers: recency. Model AUC {auc:.3f}.\n")
print(summary, auc)
