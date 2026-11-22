"""Remote access. Requests from this machine need nothing, as always; requests from anywhere else must carry the API
token (Authorization: Bearer <token>, or ?token= for downloads and the WebSocket, which cannot send headers). A request
counts as local only when it comes from a loopback address, names a loopback host (localhost, 127.0.0.1, [::1]) in its
Host header, and carries no proxy header; a local request from a browser page on another site (its Origin) is refused.

The token is made on first use (`llmdyno serve --host 0.0.0.0` or `llmdyno token`), kept in the secret store
(secrets.py: DPAPI-encrypted on Windows, an owner-only file elsewhere), and shown once; `llmdyno token --rotate` replaces it. A request that carries a proxy header (X-Forwarded-For, Forwarded,
X-Real-IP) counts as remote even when the proxy runs on this machine; a reverse proxy must send one of them
(nginx does not by default). Changes made by remote clients are logged to
<data>/logs/remote-requests.jsonl (time, client address, method, path, status)."""
from __future__ import annotations

import hmac
import ipaddress
import json
import secrets as pysecrets
import threading
import time
from urllib.parse import urlsplit

from . import config, secrets

SECRET = "api_token"
_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
_log_lock = threading.Lock()


def _loopback_name(hostname: str | None) -> bool:
    name = (hostname or "").strip().lower().rstrip(".")
    return name in _LOOPBACK_NAMES or name.endswith(".localhost")


def _host_name(host_header: str | None) -> str:
    """The name in a Host header: "localhost:8777" -> "localhost", "[::1]:8777" -> "::1"."""
    value = (host_header or "").strip()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def is_local(client_host: str | None, headers) -> bool:
    """A request from this machine that did not come through a proxy, addressed to this machine by a loopback name.

    The Host check stops DNS rebinding: a web page whose own domain is made to resolve to 127.0.0.1 reaches this server
    from a loopback address, but its requests carry that domain in Host, so they count as remote and need the token."""
    if any(h in headers for h in _PROXY_HEADERS):
        return False
    host = _host_name(headers.get("host"))
    if client_host == "testclient":                     # Starlette's in-process test client (Host: testserver)
        return host == "testserver" or _loopback_name(host)
    try:
        loopback = client_host == "localhost" or ipaddress.ip_address(client_host or "").is_loopback
    except ValueError:
        return False
    return loopback and _loopback_name(host)


def cross_site(headers) -> str | None:
    """The Origin of a browser request made by a page from another site, or None. Local requests need no token, so
    without this any website open in your browser could send requests to LLMDyno on 127.0.0.1 (a POST needs no CORS
    permission to have its effect) or read its live events over the WebSocket. Programs other than browsers send no
    Origin; the dashboard's own pages send a loopback one."""
    origin = headers.get("origin")
    if origin is None:
        return None
    if origin.strip().lower() == "null":                 # sandboxed frames, file:// pages, some redirects
        return origin
    return None if _loopback_name(urlsplit(origin.strip()).hostname) else origin


def token() -> str | None:
    return secrets.get(SECRET) or None


def ensure_token() -> tuple[str, bool]:
    """(token, created now)."""
    tok = token()
    if tok:
        return tok, False
    tok = pysecrets.token_urlsafe(32)
    secrets.set(SECRET, tok)
    return tok, True


def rotate() -> str:
    tok = pysecrets.token_urlsafe(32)
    secrets.set(SECRET, tok)
    return tok


def presented(headers, query) -> str | None:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return query.get("token") or None


def check(given: str | None) -> bool:
    tok = token()
    if not tok or not given:
        return False
    return hmac.compare_digest(tok.encode(), str(given).encode())


def log_request(client: str | None, method: str, path: str, status: int) -> None:
    folder = config.DATA / "logs"
    line = json.dumps({"ts": time.time(), "client": client, "method": method, "path": path, "status": status})
    with _log_lock:
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "remote-requests.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")


def refusal() -> str:
    if token() is None:
        return ("this LLMDyno server does not accept remote requests yet: run `llmdyno token` on it to create an "
                "access token")
    return "this LLMDyno server needs its access token: send Authorization: Bearer <token>"
