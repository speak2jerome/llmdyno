"""FastAPI app: REST API, one WebSocket for live updates, and the built web UI."""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__, config, db, events, jobs, safety
from .api import results_api, routes
from .inference import llamacpp
from .runner import sandbox

STATIC = Path(__file__).resolve().parent / "web" / "static"

@asynccontextmanager
async def lifespan(_app):
    db.init()
    events.bind(asyncio.get_running_loop())
    jobs.mark_interrupted()
    with db.Session() as s:
        for p in s.query(db.Plan).filter(db.Plan.status.in_(["running", "queued"])).all():
            p.status = "paused"           # a restart interrupts plans; queued runs can be resumed
        for r in s.query(db.Run).filter(db.Run.status.in_(["running", "grading"])).all():
            r.status, r.error, r.stage = "failed", "interrupted by a server restart", ""
        s.commit()
    await asyncio.to_thread(sandbox.cleanup_stale)
    yield
    # shutting down: nothing may keep running (or spending) without the server watching it
    await asyncio.to_thread(safety.kill_containers)
    llamacpp.server.stop(force=True)


app = FastAPI(title="LLMDyno", version=__version__, lifespan=lifespan)
app.include_router(routes.router, prefix="/api")
app.include_router(results_api.router, prefix="/api")


@app.exception_handler(KeyError)
async def key_error(_, exc):
    return JSONResponse({"detail": f"not found: {exc}"}, status_code=404)


@app.exception_handler(ValueError)
async def value_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(PermissionError)
async def perm_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=403)


@app.exception_handler(FileExistsError)
async def exists_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(FileNotFoundError)
async def missing_error(_, exc):
    return JSONResponse({"detail": str(exc) or "file or folder not found"}, status_code=400)


@app.exception_handler(ConnectionError)
async def conn_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.exception_handler(RuntimeError)
async def runtime_error(_, exc):
    # RuntimeErrors raised by LLMDyno carry user-facing explanations (missing tools, Docker problems)
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.websocket("/ws")
async def ws(socket: WebSocket):
    """One socket per browser tab. The writer waits on the reader too, so a closed tab is cleaned up at once instead
    of at the next ping; a client too slow to keep up is told to resync instead of silently missing events."""
    await socket.accept()
    q = events.ClientQueue()
    events.subscribe("jobs", q)

    async def reader():
        while True:
            msg = json.loads(await socket.receive_text())
            for t in msg.get("sub", []):
                events.subscribe(t, q)
            for t in msg.get("unsub", []):
                events.unsubscribe(q, t)

    rtask = asyncio.create_task(reader())
    try:
        while True:
            gtask = asyncio.create_task(q.get())
            done, _ = await asyncio.wait({rtask, gtask}, timeout=20, return_when=asyncio.FIRST_COMPLETED)
            if rtask in done:               # client went away (or sent garbage)
                gtask.cancel()
                break
            if gtask in done:
                batch = [gtask.result()]
            else:
                gtask.cancel()
                batch = [{"topic": "ping", "kind": "ping", "ts": time.time()}]
            while not q.empty() and len(batch) < 200:       # coalesce bursts (token deltas) into one frame
                batch.append(q.get_nowait())
            if q.overflow:
                q.overflow = False
                batch.append({"topic": "*", "kind": "resync", "ts": time.time()})
            # a stalled network must not pin this coroutine forever
            await asyncio.wait_for(socket.send_text(json.dumps(batch, default=str)), timeout=30)
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        rtask.cancel()
        events.unsubscribe(q)


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "schema_version": db.SCHEMA_VERSION, "time": time.time(),
            "data_dir": str(config.DATA)}


@app.post("/api/upload/benchmark")
async def upload_benchmark(file: UploadFile = File(...)):
    from .benchmarks import registry
    data = await file.read()
    if len(data) > 50 * 2**20:
        raise HTTPException(413, "zip larger than 50 MB")
    return registry.import_zip(data)


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    f = STATIC / full_path
    if full_path and f.is_file() and STATIC in f.resolve().parents:
        return FileResponse(f)
    index = STATIC / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return Response("<h1>LLMDyno</h1><p>The web UI is not built. Run <code>npm run build</code> in frontend/.</p>",
                    media_type="text/html")

