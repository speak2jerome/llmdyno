"""In-process pub/sub: worker threads publish, WebSocket handlers subscribe to topics."""
import asyncio
import threading
import time

_loop: asyncio.AbstractEventLoop | None = None
_subs: dict[str, set[asyncio.Queue]] = {}
_lock = threading.Lock()


def bind(loop):
    global _loop
    _loop = loop


MAX_QUEUE = 5000


class ClientQueue(asyncio.Queue):
    """A subscriber's queue. When it is full, events are dropped and overflow is set so the client refetches."""

    def __init__(self):
        super().__init__()
        self.overflow = False


def subscribe(topic, q):
    with _lock:
        _subs.setdefault(topic, set()).add(q)


def unsubscribe(q, topic=None):
    """Remove q from one topic, or from all of them; empty topics are dropped so run:<id> topics do not pile up."""
    with _lock:
        for t in [topic] if topic else list(_subs):
            qs = _subs.get(t)
            if qs is not None:
                qs.discard(q)
                if not qs:
                    del _subs[t]


def _deliver(topic, msg):
    for q in list(_subs.get(topic, ())):
        if q.qsize() < MAX_QUEUE:     # a stalled client must not grow memory without bound
            q.put_nowait(msg)
        elif isinstance(q, ClientQueue):
            q.overflow = True


_listeners: list = []                 # (callback, topic filter) for in-process listeners (the Python library)


def add_listener(fn, topics=None):
    """Call fn(msg) for every event published in this process, from the publishing thread; msg is
    {"topic", "kind", "data", "ts"}. topics limits it: a set of topics, or a function topic -> bool. Works with or
    without the web server. fn must be quick and must not raise (errors are swallowed so a listener cannot break a run).
    Returns fn, for remove_listener()."""
    if topics is not None and not callable(topics):
        wanted = set(topics)
        topics = wanted.__contains__
    with _lock:
        _listeners.append((fn, topics))
    return fn


def remove_listener(fn):
    with _lock:
        _listeners[:] = [(f, t) for f, t in _listeners if f is not fn]


def publish(topic, kind, data=None):
    """Thread-safe. Topics: jobs, job:<id>, plan:<id>, plan:<id> gpu samples, run:<id>, plans, models, profiles,
    reviews, system."""
    if _loop is None and not _listeners:
        return
    msg = {"topic": topic, "kind": kind, "data": data, "ts": time.time()}
    for fn, wants in list(_listeners):
        if wants is None or wants(topic):
            try:
                fn(msg)
            except Exception:  # noqa: BLE001 - a listener must never break the publisher (a run, a download)
                pass
    if _loop is None:
        return
    try:
        _loop.call_soon_threadsafe(_deliver, topic, msg)
    except RuntimeError:              # loop closed during shutdown
        pass
