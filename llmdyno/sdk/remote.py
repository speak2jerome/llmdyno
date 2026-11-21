"""Drive LLMDyno on another machine: every library call goes to its web API, so the same code works on a laptop
against the GPU box down the hall.

    llmdyno.connect("http://gpu-box:8777", token="...")      # or LLMDYNO_URL / LLMDYNO_TOKEN
    qwen = llmdyno.profile("Qwen 27B 32k")
    results = llmdyno.bench(qwen, "suite_quick")              # runs there; progress and results here
    llmdyno.disconnect()                                     # back to this machine

On the server: `llmdyno serve --host 0.0.0.0` (it prints the access token the first time) and keep it on a trusted
network, behind HTTPS, or reach it through an SSH tunnel (ssh -L 8777:localhost:8777 gpu-box). API keys you pass
(cloud_model(api_key=...)) are sent to the server once and stored there; they never come back over the API."""
from __future__ import annotations

import inspect
import json
import os
import re
import threading
from urllib.parse import quote

from .. import __version__
from ..errors import LLMDynoError, http
from ._backend import Backend, Subscription, _current, _switch, backend, use

__all__ = ["RemoteBackend", "connect", "disconnect", "connection"]

_ROUTES: dict = {}


def route_table() -> dict:
    """service operation -> (method, path, {parameter: "path" | "query" | "body"}), read from the API's own routes so
    it always matches this version (the server's routes call services with the same parameter names)."""
    if _ROUTES:
        return _ROUTES
    from fastapi.routing import APIRoute

    from ..server import app
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        try:
            m = re.search(r"svc_(\w+)\.(\w+)\(", inspect.getsource(r.endpoint))
        except (OSError, TypeError):
            continue
        if not m:
            continue
        where = {p.name: "path" for p in r.dependant.path_params}
        where.update({p.name: "query" for p in r.dependant.query_params})
        where.update({p.name: "body" for p in r.dependant.body_params})
        method = sorted(r.methods - {"HEAD"})[0]
        _ROUTES[f"{m.group(1)}.{m.group(2)}"] = (method, r.path, where)
    _ROUTES["benchmarks.import_benchmark_zip"] = ("POST", "/api/upload/benchmark", {"data": "file"})
    return _ROUTES


class RemoteBackend(Backend):
    """Runs every call on a LLMDyno server through its web API (httpx), and follows live events over its WebSocket."""

    kind = "remote"

    def __init__(self, url: str, token: str | None = None, *, client=None, timeout: float = 120.0,
                 verify: bool = True):
        import httpx
        self.url = url.rstrip("/")
        self.token = token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if client is None:
            client = httpx.Client(base_url=self.url, headers=headers, timeout=timeout, verify=verify)
        else:
            client.headers.update(headers)
        self.http = client
        self.routes = route_table()

    def __repr__(self):
        return f"<llmdyno backend remote {self.url}>"

    # -- calls
    def call(self, op: str, **kwargs):
        if op not in self.routes:
            raise LLMDynoError(f"{op} is not available over the web API")
        method, path, where = self.routes[op]
        if where.get("data") == "file":
            r = self.http.post(path, files={"file": ("benchmark.zip", kwargs["data"], "application/zip")})
            return self._result(r)
        url = path
        for name, kind in where.items():
            if kind == "path":
                url = url.replace("{" + name + "}", quote(str(kwargs[name]), safe=""))
        params = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in kwargs.items()
                  if where.get(k) == "query" and v is not None}
        body = next((kwargs[k] for k, kind in where.items() if kind == "body" and k in kwargs), None)
        unknown = set(kwargs) - set(where)
        if unknown:
            raise TypeError(f"{op} takes no {', '.join(sorted(unknown))}")
        r = self.http.request(method, url, params=params, json=body)
        return self._result(r)

    @staticmethod
    def _result(r):
        ctype = r.headers.get("content-type", "")
        if r.status_code >= 400:
            detail = None
            if "json" in ctype:
                try:
                    detail = r.json().get("detail")
                except ValueError:
                    detail = None
            raise http(r.status_code, detail or r.text or f"HTTP {r.status_code}")
        disp = r.headers.get("content-disposition", "")
        if "attachment" in disp:
            m = re.search(r'filename="?([^";]+)"?', disp)
            media = ctype.split(";")[0].strip()
            textual = media.startswith("text/") or media in ("application/json", "application/x-ndjson")
            return {"download": True, "filename": m.group(1) if m else "download", "media_type": media,
                    "content": r.text if textual else r.content}
        if "json" in ctype:
            return r.json()
        return r.text

    def health(self) -> dict:
        return self._result(self.http.get("/api/health"))

    # -- live events over the WebSocket
    def subscribe(self, fn, wanted, names=()):
        try:
            return _WsSubscription(self, fn, wanted, list(names))
        except Exception:  # noqa: BLE001 - no WebSocket (a proxy that blocks it, say): watch() polls instead
            return None

    @property
    def ui_url(self) -> str:
        return self.url


class _WsSubscription(Subscription):
    """A thread reading the server's WebSocket and passing wanted events on."""

    def __init__(self, remote: RemoteBackend, fn, wanted, names: list):
        super().__init__()
        self.fn, self.wanted, self.stop = fn, wanted, threading.Event()
        self.lock = threading.Lock()
        query = f"?token={quote(remote.token)}" if remote.token else ""
        from starlette.testclient import TestClient
        if isinstance(remote.http, TestClient):                  # the in-process server the tests use
            self._cm = remote.http.websocket_connect("/ws" + query)
            sess = self._cm.__enter__()
            self._send, self._recv = sess.send_text, sess.receive_text
            self._closer = lambda: self._cm.__exit__(None, None, None)
        else:
            from websockets.sync.client import connect as ws_connect
            ws_url = re.sub(r"^http", "ws", remote.url) + "/ws" + query
            conn = ws_connect(ws_url, open_timeout=10, max_size=2**24)
            self._send, self._recv, self._closer = conn.send, conn.recv, conn.close
        if names:
            self.add_many(names)
        self.thread = threading.Thread(target=self._read, daemon=True, name="llmdyno-remote-events")
        self.thread.start()

    def add_many(self, topics: list) -> None:
        with self.lock:
            self._send(json.dumps({"sub": list(topics)}))

    def add(self, topic: str) -> None:
        if not self.stop.is_set():
            self.add_many([topic])

    def _read(self):
        while not self.stop.is_set():
            try:
                batch = json.loads(self._recv())
            except Exception:  # noqa: BLE001 - the socket closed; watch() keeps polling
                return
            for msg in batch if isinstance(batch, list) else [batch]:
                topic = msg.get("topic") or ""
                if topic not in ("ping", "*") and self.wanted(topic):
                    self.fn(msg)

    def close(self) -> None:
        if not self.stop.is_set():
            self.stop.set()
            try:
                self._closer()
            except Exception:  # noqa: BLE001 - already closed
                pass


def connect(url: str | None = None, token: str | None = None, *, timeout: float = 120.0, verify: bool = True,
            client=None) -> RemoteBackend:
    """Send every later llmdyno call to the LLMDyno server at url (default LLMDYNO_URL), authenticating with its
    access token (default LLMDYNO_TOKEN; not needed on the server's own machine). Returns the connection."""
    url = url or os.environ.get("LLMDYNO_URL")
    if not url:
        raise LLMDynoError("connect() needs the server's URL, e.g. http://gpu-box:8777 (or set LLMDYNO_URL)")
    token = token or os.environ.get("LLMDYNO_TOKEN")
    remote = RemoteBackend(url, token, timeout=timeout, verify=verify, client=client)
    try:
        info = remote.health()
    except LLMDynoError as e:
        if getattr(e, "status", None) == 401:
            raise LLMDynoError(f"{url} refused the connection: {e}. Pass token= (shown by `llmdyno token` on the "
                               "server) or set LLMDYNO_TOKEN.") from None
        raise
    except Exception as e:  # noqa: BLE001 - network errors, wrong URL
        raise LLMDynoError(f"cannot reach LLMDyno at {url}: {type(e).__name__}: {e}") from None
    if not isinstance(info, dict) or not info.get("ok"):
        raise LLMDynoError(f"{url} does not look like a LLMDyno server")
    theirs, ours = str(info.get("version", "")).split(".")[:2], __version__.split(".")[:2]
    if theirs != ours:
        import warnings
        warnings.warn(f"the server runs LLMDyno {info.get('version')} and this library is {__version__}; calls that "
                      "changed between them may fail", stacklevel=2)
    remote.server = info
    use(remote)
    return remote


def disconnect() -> None:
    """Go back to running everything on this machine."""
    with _switch:
        _current["backend"] = None


def connection() -> Backend:
    """Where calls go now: a LocalBackend, or the RemoteBackend from connect()."""
    return backend()

