# pyright: strict, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""The web dashboard: start it on this data folder, or open a page of it."""
from __future__ import annotations

from typing import Any

import threading
import time
import webbrowser

from ..errors import LLMDynoError
from ._backend import LocalBackend, backend

__all__ = ["serve"]

_server: dict[str, Any] = {"thread": None, "url": None}


def _ui_url(port: Any=None):
    from .. import config
    return f"http://127.0.0.1:{port or int(config.get('port'))}"


def _ui_up(url: Any) -> bool:
    import httpx
    try:
        return httpx.get(url + "/api/health", timeout=1.5).status_code < 500
    except httpx.HTTPError:
        return False


def serve(port: int | None = None, *, open_browser: bool = True, block: bool = True) -> str:
    """Start the dashboard on this data folder. block=False runs it in a background thread (handy in notebooks)."""
    b = backend()
    if not isinstance(b, LocalBackend):
        raise LLMDynoError("serve() starts the dashboard on this machine; a remote LLMDyno already serves its own")
    if not b.ready:
        b.start()
    import uvicorn
    url = _ui_url(port)
    if _ui_up(url):
        if open_browser:
            webbrowser.open(url)
        return url
    from .. import config
    cfg = uvicorn.Config("llmdyno.server:app", host="127.0.0.1", port=port or int(config.get("port")), log_level="warning")
    server = uvicorn.Server(cfg)
    if block:
        if open_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"LLMDyno on {url}  (data: {config.DATA}); Ctrl+C stops it", flush=True)
        server.run()
        return url
    t = threading.Thread(target=server.run, daemon=True, name="llmdyno-ui")
    t.start()
    for _ in range(60):
        if _ui_up(url):
            break
        time.sleep(0.25)
    _server.update(thread=t, url=url)
    if open_browser:
        webbrowser.open(url)
    return url


def open_ui(path: str) -> str:
    b = backend()
    if not isinstance(b, LocalBackend):                   # connected to a remote LLMDyno: open its dashboard
        from urllib.parse import quote
        base = getattr(b, "ui_url", None)
        if not base:
            raise LLMDynoError("this connection has no dashboard to open")
        token = getattr(b, "token", None)
        url = base + path + (f"#token={quote(token)}" if token else "")    # the page keeps it; it never reaches logs
        webbrowser.open(url)
        return base + path
    url = _ui_url()
    if not _ui_up(url):
        serve(open_browser=False, block=False)
    webbrowser.open(url + path)
    return url + path
