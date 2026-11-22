# pyright: strict, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""Where SDK calls go.

Every SDK call is `call("area.function", **kwargs)`: a function in llmdyno/services with its parameters by name. The
backend decides how that call is made:

* LocalBackend (the default) runs the service in this process, on this machine's data folder.
* RemoteBackend (llmdyno.connect()) sends the same call to a LLMDyno server over HTTP.

Both return the same plain data and raise the same llmdyno.errors, so SDK objects behave the same either way. SDK code
must not import the database or engine modules directly; anything it needs goes through a service."""
from __future__ import annotations

import atexit
import importlib
import threading
from pathlib import Path
from typing import Any, Callable, Sequence

Message = dict[str, Any]


class Backend:
    """How the SDK reaches LLMDyno. Subclasses implement call()."""

    kind = "abstract"

    def call(self, op: str, **kwargs: Any) -> Any:
        """Run the service function `op` ("area.function") with keyword arguments and return its result."""
        raise NotImplementedError

    def subscribe(self, fn: Callable[[Message], None], wanted: Callable[[str], bool],
                  names: Sequence[str] = ()) -> "Subscription | None":
        """Call fn(msg) for live events whose topic passes wanted(topic). names are the topics to ask for (a remote
        server sends only what was asked for); more can be added later with the returned Subscription's add().
        A backend without live events returns None and watch() falls back to polling."""
        return None

    def __repr__(self) -> str:
        return f"<llmdyno backend {self.kind}>"


class LocalBackend(Backend):
    """Runs the services in this process, on the local data folder (LLMDYNO_DATA, init(), or the default)."""

    kind = "local"

    def __init__(self) -> None:
        self._ready = False
        self._lock = threading.Lock()

    def start(self, data_dir: str | Path | None = None) -> Path:
        """Open (and create if needed) the data folder; with a folder, switch to it."""
        from .. import config, db
        with self._lock:
            if data_dir is not None:
                config.set_data_dir(data_dir)
            db.init()
            self._ready = True
            _register_exit_hook()
        return config.DATA

    @property
    def ready(self) -> bool:
        """Whether the data folder is open."""
        return self._ready

    def call(self, op: str, **kwargs: Any) -> Any:
        if not self._ready:
            self.start()
        fn = resolve(op)
        try:
            return fn(**kwargs)
        except Exception as e:
            from ..errors import from_exception
            err = from_exception(e)               # the same error the web API would answer with
            if err is None or err is e:
                raise
            raise err from e

    def subscribe(self, fn: Callable[[Message], None], wanted: Callable[[str], bool],
                  names: Sequence[str] = ()) -> "Subscription | None":
        """In-process events: plans, downloads and reviews started from this process publish here directly.
        (Work running in another process, such as a separate web server, is seen by watch() through polling.)"""
        from .. import events
        events.add_listener(fn, wanted)
        return Subscription(close=lambda: events.remove_listener(fn))


def resolve(op: str) -> Callable[..., Any]:
    """The service function behind "area.function"."""
    area, _, name = op.partition(".")
    if not name or area.startswith("_") or name.startswith("_"):
        raise ValueError(f"not a service operation: {op!r}")
    return getattr(importlib.import_module(f"llmdyno.services.{area}"), name)


class Subscription:
    """A live-event subscription: add(topic) asks for one more topic, close() ends it."""

    def __init__(self, close: Callable[[], None] | None = None, add: Callable[[str], None] | None = None) -> None:
        self._close, self._add = close, add

    def add(self, topic: str) -> None:
        if self._add:
            self._add(topic)

    def close(self) -> None:
        if self._close:
            self._close()
            self._close = None


_exit_hook = {"done": False}


def _register_exit_hook() -> None:
    """Stop a llama-server this process started when the interpreter exits."""
    if _exit_hook["done"]:
        return
    _exit_hook["done"] = True

    def stop() -> None:
        try:
            from ..inference import llamacpp
            llamacpp.server.stop(force=True)
        except Exception:  # noqa: BLE001 - best effort at interpreter exit
            pass
    atexit.register(stop)


_current: dict[str, Backend | None] = {"backend": None}
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


def use(b: Backend) -> Backend | None:
    """Install a backend for every later SDK call; returns the previous one."""
    if not isinstance(b, Backend):  # pyright: ignore[reportUnnecessaryIsInstance] - callers may not be typed
        raise TypeError("use() takes a Backend")
    with _switch:
        prev, _current["backend"] = _current["backend"], b
    return prev


def reset() -> None:
    """Forget the installed backend: the next call starts a LocalBackend again."""
    with _switch:
        _current["backend"] = None


def call(op: str, **kwargs: Any) -> Any:
    """Run a service operation through the current backend."""
    return backend().call(op, **kwargs)
