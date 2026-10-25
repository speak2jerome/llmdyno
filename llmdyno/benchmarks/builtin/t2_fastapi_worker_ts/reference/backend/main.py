import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import connect, row_to_job

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI()
dist = ROOT / "frontend" / "dist"
dist.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=dist), name="static")


class JobIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    operation: Literal["wordcount", "uppercase", "reverse_words", "summary"]


def db():
    return connect(os.environ.get("JOBS_DB", "./jobs.db"))


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.post("/api/jobs", status_code=201)
def create(job: JobIn):
    con = db()
    cur = con.execute("INSERT INTO jobs (text, operation, status, created_at) VALUES (?,?,?,?)",
                      (job.text, job.operation, "queued", datetime.now(timezone.utc).isoformat()))
    con.commit()
    return row_to_job(con.execute("SELECT * FROM jobs WHERE id=?", (cur.lastrowid,)).fetchone())


@app.get("/api/jobs/{job_id}")
def get(job_id: int):
    row = db().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row_to_job(row)


@app.get("/api/jobs")
def list_jobs(status: Optional[str] = None):
    q, args = "SELECT * FROM jobs", ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    return [row_to_job(r) for r in db().execute(q + " ORDER BY id DESC", args)]


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: int):
    con = db()
    row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    cur = con.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status='queued'", (job_id,))
    con.commit()
    if cur.rowcount == 0:
        raise HTTPException(409)
    return row_to_job(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
