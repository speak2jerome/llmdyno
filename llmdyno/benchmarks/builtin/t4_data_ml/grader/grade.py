import json
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, "/grader_common")
from grading import WORK, emit, run  # noqa: E402

HERE = Path(__file__).parent
truth = json.loads((HERE / "truth.json").read_text())
tf = pd.read_parquet(HERE / "truth_features.parquet").set_index("customer_id")
labels = pd.read_csv(HERE / "test_labels.csv")
OUT = WORK / "output"
tests, checks, extra = {}, {}, {}


def safe(name, fn):
    try:
        tests[name] = bool(fn())
    except Exception as e:  # any crash in reading/validating an artifact = failed test
        tests[name] = False
        extra.setdefault("errors", {})[name] = f"{type(e).__name__}: {e}"[:300]


# ---- features.parquet ----
feat = None
try:
    feat = pd.read_parquet(OUT / "features.parquet")
    feat["customer_id"] = feat["customer_id"].astype(str)
    feat = feat.set_index("customer_id")
except Exception as e:
    extra["features_error"] = str(e)[:300]

REQUIRED = ["signup_date", "country", "plan", "age", "n_events", "n_purchases", "total_amount",
            "n_support_tickets", "days_since_last_event", "churned"]


def frac_match(col, tol=None):
    joined = feat[[col]].join(tf[[col]], rsuffix="_t", how="inner")
    if len(joined) != len(tf):
        return 0.0
    a, b = joined[col], joined[col + "_t"]
    if tol is None:
        eq = a.astype(str).str.strip() == b.astype(str).str.strip()
    else:
        eq = (pd.to_numeric(a, errors="coerce") - pd.to_numeric(b, errors="coerce")).abs() <= tol
    return float(eq.mean())


safe("features_row_count", lambda: len(feat) == truth["n_customers"] and feat.index.is_unique)
safe("features_columns", lambda: all(c in feat.columns for c in REQUIRED))
safe("features_country_normalized", lambda: frac_match("country") >= 0.99)
safe("features_plan_normalized", lambda: frac_match("plan") >= 0.99)
safe("features_age_imputed", lambda: frac_match("age", tol=0.01) >= 0.99)
safe("features_event_counts", lambda: min(frac_match(c, tol=0) for c in ("n_events", "n_purchases", "n_support_tickets")) >= 0.99)
safe("features_total_amount", lambda: frac_match("total_amount", tol=0.02) >= 0.99)
safe("features_days_since_last_event", lambda: frac_match("days_since_last_event", tol=0) >= 0.99)
safe("features_signup_date_dedup", lambda: (pd.to_datetime(feat["signup_date"]).dt.strftime("%Y-%m-%d")
                                           .reindex(tf.index) == tf["signup_date"]).mean() >= 0.99)


def churn_labels_ok():
    train_ids = set(pd.read_csv(WORK / "data" / "labels_train.csv")["customer_id"])
    lab = pd.to_numeric(feat["churned"], errors="coerce")
    test_rows = lab[~lab.index.isin(train_ids)]
    train_rows = lab[lab.index.isin(train_ids)]
    return test_rows.isna().all() and train_rows.notna().all()


safe("features_churned_only_for_train", churn_labels_ok)


def warehouse_ok():
    con = sqlite3.connect(OUT / "warehouse.db")
    try:
        n = con.execute("SELECT COUNT(*) FROM features").fetchone()[0]
        cols = [r[1] for r in con.execute("PRAGMA table_info(features)")]
    finally:
        con.close()
    return n == truth["n_customers"] and all(c in cols for c in ["customer_id", *REQUIRED])


safe("warehouse_features_table", warehouse_ok)

# ---- summary.json ----
summary = {}
try:
    summary = json.loads((OUT / "summary.json").read_text())
except Exception as e:
    extra["summary_error"] = str(e)[:300]
safe("summary_n_customers", lambda: int(summary["n_customers"]) == truth["n_customers"])
safe("summary_n_events_clean", lambda: int(summary["n_events_clean"]) == truth["n_events_clean"])
safe("summary_train_churn_rate", lambda: abs(float(summary["train_churn_rate"]) - truth["train_churn_rate"]) <= 0.0005)
safe("summary_median_age", lambda: abs(float(summary["median_age"]) - truth["median_age"]) <= 0.01)
safe("summary_top_countries", lambda: list(summary["top_countries_by_revenue"]) == truth["top_countries_by_revenue"])
safe("summary_revenue_by_month", lambda: all(
    abs(float(summary["revenue_by_month_2026"][m]) - v) <= max(1.0, 0.005 * v)
    for m, v in truth["revenue_by_month_2026"].items()))

# ---- model ----
auc = None
try:
    pred = pd.read_csv(OUT / "predictions.csv")
    merged = labels.merge(pred, on="customer_id", how="left")
    complete = merged["churn_probability"].notna().all() and len(pred) == len(labels) and pred["customer_id"].is_unique
    probs = merged["churn_probability"].astype(float)
    valid = complete and probs.between(0, 1).all()
    tests["predictions_complete_and_valid"] = bool(valid)
    if complete:
        auc = float(roc_auc_score(merged["churned"], probs.fillna(0.5)))
except Exception as e:
    tests["predictions_complete_and_valid"] = False
    extra["predictions_error"] = str(e)[:300]
ref = truth["reference_test_auc"]
tests["model_auc_ge_0.75"] = auc is not None and auc >= 0.75
tests["model_auc_within_0.04_of_reference"] = auc is not None and auc >= ref - 0.04
tests["model_auc_within_0.015_of_reference"] = auc is not None and auc >= ref - 0.015
extra["test_auc"] = auc
extra["reference_auc"] = ref

# ---- reproducibility: rerun the pipeline from scratch in a clean copy ----
clean = Path("/tmp/repro")
shutil.rmtree(clean, ignore_errors=True)
shutil.copytree(WORK, clean, ignore=shutil.ignore_patterns("output", "__pycache__", ".pytest_cache"))
code, _, err = run([sys.executable, "pipeline.py"], cwd=clean, timeout=330)
repro = False
try:
    s2 = json.loads((clean / "output" / "summary.json").read_text())
    repro = code == 0 and int(s2["n_customers"]) == truth["n_customers"] and (clean / "output" / "predictions.csv").exists()
except Exception:
    pass
tests["pipeline_reproducible"] = repro
if not repro:
    extra["repro_stderr"] = err[-500:]

# ---- instruction-following checks ----
report = (OUT / "report.md").read_text(errors="ignore") if (OUT / "report.md").exists() else ""
metrics = {}
try:
    metrics = json.loads((OUT / "metrics.json").read_text())
except Exception:
    pass
EXPECTED_KEYS = {"n_customers", "n_events_clean", "train_churn_rate", "median_age", "top_countries_by_revenue",
                 "revenue_by_month_2026"}
checks = {
    "summary_has_exactly_required_keys": set(summary) == EXPECTED_KEYS,
    "report_has_revenue_table": "|" in report and "2026-0" in report,
    "report_mentions_customer_count": str(truth["n_customers"]) in report.replace(",", ""),
    "report_discusses_drivers_and_model": all(k in report.lower() for k in ("churn", "auc")),
    "metrics_json_valid": isinstance(metrics.get("model"), str) and 0.5 <= float(metrics.get("cv_auc", 0)) <= 1.0,
    "predictions_columns_exact": (OUT / "predictions.csv").exists() and
        list(pd.read_csv(OUT / "predictions.csv", nrows=1).columns) == ["customer_id", "churn_probability"],
    "pipeline_py_present": (WORK / "pipeline.py").exists(),
}
extra["reported_cv_auc"] = metrics.get("cv_auc")
emit(tests, checks, extra)
