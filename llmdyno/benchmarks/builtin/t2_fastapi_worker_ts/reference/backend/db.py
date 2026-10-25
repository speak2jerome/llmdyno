import json
import sqlite3

SCHEMA = """CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, operation TEXT,
status TEXT, result TEXT, error TEXT, created_at TEXT, finished_at TEXT)"""


def connect(path):
    con = sqlite3.connect(path, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def row_to_job(r):
    d = dict(r)
    d["result"] = json.loads(d["result"]) if d["result"] is not None else None
    return d
