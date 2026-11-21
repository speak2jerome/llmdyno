"""Remote access. Requests from this machine need nothing, as always; requests from anywhere else must carry the API
token (Authorization: Bearer <token>, or ?token= for downloads and the WebSocket, which cannot send headers).

The token is made on first use (`llmdyno serve --host 0.0.0.0` or `llmdyno token`), kept in the encrypted secret store,
and shown once; `llmdyno token --rotate` replaces it. A request that went through a proxy (X-Forwarded-For, Forwarded,
X-Real-IP) counts as remote even when the proxy runs on this machine. Changes made by remote clients are logged to
<data>/logs/remote-requests.jsonl (time, client address, method, path, status)."""
from __future__ import annotations

import hmac
import ipaddress
import json
import secrets as pysecrets
import threading
import time

from . import config, secrets

SECRET = "api_token"
_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
_log_lock = threading.Lock()


def is_local(client_host: str | None, headers) -> bool:
    """A request from this machine that did not come through a proxy."""
    if any(h in headers for h in _PROXY_HEADERS):
        return False
    if client_host in ("testclient", "localhost"):          # Starlette's in-process test client
        return True
    try:
        return ipaddress.ip_address(client_host or "").is_loopback
    except ValueError:
        return False


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
    return bool(tok and given) and hmac.compare_digest(tok.encode(), str(given).encode())


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
