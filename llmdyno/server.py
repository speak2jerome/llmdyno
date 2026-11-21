"""FastAPI app: REST API, one WebSocket for live updates, and the built web UI."""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__, auth, config, db, errors, events, jobs, safety
from .api import external_api, results_api, routes
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
app.include_router(external_api.router, prefix="/api")


async def _error(_, exc):
    """One mapping for every error, shared with the Python library (errors.from_exception): the body is
    {"detail": message} with the status that error means."""
    err = errors.from_exception(exc)
    return JSONResponse({"detail": str(err)}, status_code=err.status)


for _cls in (errors.LLMDynoError, KeyError, ValueError, PermissionError, FileExistsError, FileNotFoundError,
             ConnectionError, RuntimeError):
    app.add_exception_handler(_cls, _error)


@app.middleware("http")
async def remote_access(request, call_next):
    """This machine needs nothing; other machines need the API token (auth.py). Changes they make are logged."""
    if not request.url.path.startswith("/api"):
        return await call_next(request)                  # the web UI's own files carry no data
    client = request.client.host if request.client else None
    if auth.is_local(client, request.headers):
        return await call_next(request)
    if not auth.check(auth.presented(request.headers, request.query_params)):
        return JSONResponse({"detail": auth.refusal()}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    response = await call_next(request)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        auth.log_request(forwarded or client, request.method, request.url.path, response.status_code)
    return response


@app.websocket("/ws")
async def ws(socket: WebSocket):
    """One socket per browser tab. The writer waits on the reader too, so a closed tab is cleaned up at once instead
    of at the next ping; a client too slow to keep up is told to resync instead of silently missing events.
    Remote clients pass the API token as ?token= (browsers cannot set headers on a WebSocket)."""
    client = socket.client.host if socket.client else None
    if not auth.is_local(client, socket.headers) and not auth.check(auth.presented(socket.headers, socket.query_params)):
        await socket.close(code=1008)
        return
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
    from .services import benchmarks as svc_benchmarks
    return svc_benchmarks.import_benchmark_zip(data=await file.read())


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

