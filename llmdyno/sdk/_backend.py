"""Where SDK calls go.

Every SDK call is `call("area.function", **kwargs)`: a function in llmdyno/services with its parameters by name. The
backend decides how that call is made:

* LocalBackend (the default) runs the service in this process, on this machine's data folder.
* RemoteBackend (llmdyno.connect, coming in 0.6) will send the same call to a LLMDyno server over HTTP.

Both return the same plain data and raise the same llmdyno.errors, so SDK objects behave the same either way. SDK code
must not import the database or engine modules directly; anything it needs goes through a service."""
from __future__ import annotations

import atexit
import importlib
import threading
from pathlib import Path


class Backend:
    """How the SDK reaches LLMDyno. Subclasses implement call()."""

    kind = "abstract"

    def call(self, op: str, **kwargs):
        """Run the service function `op` ("area.function") with keyword arguments and return its result."""
        raise NotImplementedError

    def subscribe(self, fn, topics):
        """Call fn(msg) for live events whose topic passes topics(topic); return a function that unsubscribes.
        A backend without live events returns None and watch() falls back to polling."""
        return None

    def __repr__(self):
        return f"<llmdyno backend {self.kind}>"


class LocalBackend(Backend):
    """Runs the services in this process, on the local data folder (LLMDYNO_DATA, init(), or the default)."""

    kind = "local"

    def __init__(self):
        self._ready = False
        self._lock = threading.Lock()

    def start(self, data_dir=None) -> Path:
        """Open (and create if needed) the data folder; with a folder, switch to it."""
        from .. import config, db
        with self._lock:
            if data_dir is not None:
                config.set_data_dir(data_dir)
            db.init()
            self._ready = True
            _register_exit_hook()
        return config.DATA

    def call(self, op: str, **kwargs):
        if not self._ready:
            self.start()
        return resolve(op)(**kwargs)

    def subscribe(self, fn, topics):
        """In-process events: plans, downloads and reviews started from this process publish here directly.
        (Work running in another process, such as a separate web server, is seen by watch() through polling.)"""
        from .. import events
        events.add_listener(fn, topics)
        return lambda: events.remove_listener(fn)


def resolve(op: str):
    """The service function behind "area.function"."""
    area, _, name = op.partition(".")
    if not name or area.startswith("_") or name.startswith("_"):
        raise ValueError(f"not a service operation: {op!r}")
    return getattr(importlib.import_module(f"llmdyno.services.{area}"), name)


_exit_hook = {"done": False}


def _register_exit_hook():
    """Stop a llama-server this process started when the interpreter exits."""
    if _exit_hook["done"]:
        return
    _exit_hook["done"] = True

    def stop():
        try:
            from ..inference import llamacpp
            llamacpp.server.stop(force=True)
        except Exception:  # noqa: BLE001 - best effort at interpreter exit
            pass
    atexit.register(stop)


_current: dict = {"backend": None}
_switch = threading.Lock()


def backend() -> Backend:
    """The backend in use (a LocalBackend unless something else was installed with use())."""
    b = _current["backend"]
    if b is None:
        with _switch:
            if _current["backend"] is None:
                _current["backend"] = LocalBackend()
            b = _current["backend"]
    return b


def use(b: Backend) -> Backend:
    """Install a backend for every later SDK call; returns the previous one."""
    if not isinstance(b, Backend):
        raise TypeError("use() takes a Backend")
    with _switch:
        prev, _current["backend"] = _current["backend"], b
    return prev


def call(op: str, **kwargs):
    """Run a service operation through the current backend."""
    return backend().call(op, **kwargs)
