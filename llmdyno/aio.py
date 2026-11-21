"""Async versions of the library, for asyncio code and notebooks with a running event loop.

    from llmdyno import aio

    qwen = await aio.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL")
    plan = await aio.bench(qwen, "suite_quick", wait=False)
    async for ev in aio.watch(plan):
        print(ev.kind, ev.status)
    results = await aio.call(plan.results)

Every public llmdyno function is available here as a coroutine function that runs in a worker thread
(asyncio.to_thread), so the event loop stays responsive while a plan runs or a model downloads. The objects they
return (Profile, Plan, Results, …) are the normal ones; await aio.call(obj.method, ...) runs any of their methods
the same way."""
from __future__ import annotations

import asyncio
import functools
import threading

__all__ = ["call", "watch"]

_END = object()


async def call(fn, *args, **kwargs):
    """Run any blocking llmdyno call (a function or a method) in a worker thread."""
    return await asyncio.to_thread(fn, *args, **kwargs)


async def watch(target, **kwargs):
    """llmdyno.watch() as an async iterator. Leaving the loop early stops the watcher."""
    from . import lib
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def pump():
        try:
            for ev in lib.watch(target, _stop=stop, **kwargs):
                loop.call_soon_threadsafe(q.put_nowait, ev)
        except BaseException as e:  # noqa: BLE001 - handed to the awaiting side
            loop.call_soon_threadsafe(q.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, _END)

    worker = asyncio.ensure_future(asyncio.to_thread(pump))
    try:
        while True:
            item = await q.get()
            if item is _END:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stop.set()
        await asyncio.shield(worker)


def __getattr__(name):
    from . import lib
    fn = getattr(lib, name, None) if name in lib.__all__ else None
    if fn is None or isinstance(fn, type) or not callable(fn):
        raise AttributeError(f"module 'llmdyno.aio' has no attribute {name!r}")

    @functools.wraps(fn)
    async def run(*args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)
    globals()[name] = run
    return run


def __dir__():
    from . import lib
    return sorted(set(globals()) | {n for n in lib.__all__ if callable(getattr(lib, n)) and not isinstance(getattr(lib, n), type)})
