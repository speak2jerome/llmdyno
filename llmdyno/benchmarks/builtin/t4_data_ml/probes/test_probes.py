"""Beyond-spec robustness probes for the data pipeline: rerun it on slightly messier input.

Each edge case runs in its own copy of the workspace, so one crash fails only the probe it belongs to.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

WORK = Path(os.environ.get("WORK", "/work"))

# in-spec additions: new customers with name/punctuated country, padded plan, float-valued age
NEW_CUSTOMERS = "C99901,2025/02/03,germany ,30,  PRO \nC99902,2025-05-06,  U.S.,45.0,basic\n"
NEW_EVENTS = json.dumps({"customer_id": "C99902", "ts": "2026-03-02T11:00:00Z", "event_type": "login",
                         "amount": None}) + "\n"


def scenario(factory, name, customers="", events="", runs=1):
    d = factory.mktemp(name)
    shutil.copytree(WORK, d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("output", "__pycache__"))
    # an empty output/ as in the agent's workspace: the grader's reproducibility test already charges a pipeline
    # that does not create it
    (d / "output").mkdir(exist_ok=True)
    for fname, extra in (("customers.csv", customers), ("events.jsonl", events)):
        if extra:
            p = d / "data" / fname
            text = p.read_text()
            p.write_text(text + ("" if text.endswith("\n") else "\n") + extra)
    out = []
    for _ in range(runs):
        p = subprocess.run([sys.executable, "pipeline.py"], cwd=d, capture_output=True, text=True, timeout=330)
        summary = (d / "output" / "summary.json").read_text() if (d / "output" / "summary.json").exists() else None
        out.append((p.returncode, summary, p.stderr[-800:]))
    return d, out


def features(d):
    return pd.read_parquet(d / "output" / "features.parquet").set_index("customer_id")


@pytest.fixture(scope="module")
def in_spec(tmp_path_factory):
    return scenario(tmp_path_factory, "in_spec", NEW_CUSTOMERS, NEW_EVENTS, runs=2)


def test_new_customers_counted(in_spec):
    _, runs = in_spec
    assert runs[0][0] == 0, runs[0][2]
    assert json.loads(runs[0][1])["n_customers"] == 4002


def test_float_string_age_parsed(in_spec):
    d, runs = in_spec
    assert runs[0][0] == 0, runs[0][2]
    f = features(d)
    assert float(f.loc["C99902", "age"]) == 45.0
    assert f.loc["C99902", "country"] == "US" and f.loc["C99901", "country"] == "DE" and f.loc["C99901", "plan"] == "pro"


def test_rerun_is_deterministic(in_spec):
    _, runs = in_spec
    assert runs[0][1] is not None and runs[0][1] == runs[1][1]


def test_padded_amount_counted(tmp_path_factory):
    event = json.dumps({"customer_id": "C99901", "ts": "2026-03-01T10:00:00Z", "event_type": "purchase",
                        "amount": " 12.50 ", "channel": "web"}) + "\n"
    d, runs = scenario(tmp_path_factory, "padded_amount", NEW_CUSTOMERS, NEW_EVENTS + event)
    assert runs[0][0] == 0, runs[0][2]
    assert abs(float(features(d).loc["C99901", "total_amount"]) - 12.5) < 0.01


def test_non_numeric_age_is_imputed(tmp_path_factory):
    d, runs = scenario(tmp_path_factory, "bad_age", NEW_CUSTOMERS + "C99903,2025-07-08,FR,abc,basic\n")
    assert runs[0][0] == 0, runs[0][2]
    assert 16 <= float(features(d).loc["C99903", "age"]) <= 100


def test_blank_line_in_events_tolerated(tmp_path_factory):
    _, runs = scenario(tmp_path_factory, "blank_line", NEW_CUSTOMERS, "\n" + NEW_EVENTS + "\n")
    assert runs[0][0] == 0, runs[0][2]
    assert json.loads(runs[0][1])["n_customers"] == 4002
