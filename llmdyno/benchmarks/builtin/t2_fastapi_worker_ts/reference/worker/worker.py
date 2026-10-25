import json
import os
import re
import time
from datetime import datetime, timezone

from backend.db import connect


def compute(op, text):
    if op == "wordcount":
        return {"words": len(text.split()), "chars": len(text)}
    if op == "uppercase":
        return text.upper()
    if op == "reverse_words":
        return " ".join(reversed(text.split()))
    if op == "summary":
        m = re.search(r"[.!?]", text.strip())
        s = text.strip()[: m.end()] if m else text.strip()
        return s.strip()[:100]
    raise ValueError(f"unknown operation {op}")


def process_next_job(db_path):
    con = connect(db_path)
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
    if not row:
        con.execute("COMMIT")
        return False
    con.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
    con.execute("COMMIT")
    now = lambda: datetime.now(timezone.utc).isoformat()
    try:
        res = compute(row["operation"], row["text"])
        con.execute("UPDATE jobs SET status='done', result=?, finished_at=? WHERE id=?", (json.dumps(res), now(), row["id"]))
    except Exception as e:
        con.execute("UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?", (str(e), now(), row["id"]))
    return True


def main():
    while True:
        if not process_next_job(os.environ.get("JOBS_DB", "./jobs.db")):
            time.sleep(0.5)


if __name__ == "__main__":
    main()
