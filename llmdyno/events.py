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


def publish(topic, kind, data=None):
    """Thread-safe. Topics: jobs, job:<id>, plan:<id>, run:<id>, models, system."""
    if _loop is None:
        return
    msg = {"topic": topic, "kind": kind, "data": data, "ts": time.time()}
    try:
        _loop.call_soon_threadsafe(_deliver, topic, msg)
    except RuntimeError:              # loop closed during shutdown
        pass
