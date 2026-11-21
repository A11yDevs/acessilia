"""Bridging asynchronous SDK calls into synchronous code."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine from synchronous code, inside or outside an event loop.

    Outside a running loop this is ``asyncio.run`` in the calling thread.
    Inside one, ``asyncio.run`` would raise, so the coroutine runs on a fresh
    loop in a worker thread, inside a copy of the caller's :mod:`contextvars`
    context so operation identifiers and other request-scoped variables
    propagate across the thread boundary.

    Blocking contract:
        When this thread already has a running loop, ``run_sync`` blocks that
        loop until the worker thread finishes: it is a synchronous bridge, not
        a non-blocking offload.  Every task on the calling loop stays stalled
        for the whole duration of the coroutine, so an async caller must not
        invoke a synchronous entrypoint that reaches ``run_sync`` directly.
        Wrap that entrypoint in ``asyncio.to_thread`` (in this service,
        :func:`acessilia_core.blocking.run_blocking`) and ``await`` the result
        instead.

    Coroutine ownership:
        ``run_sync`` consumes the coroutine object.  If the worker setup fails
        before an event loop takes ownership -- while copying the context,
        creating the executor, or submitting the work -- the coroutine is
        closed before the error propagates, so the failure cannot surface later
        as ``RuntimeWarning: coroutine ... was never awaited``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    submitted = False
    try:
        context = contextvars.copy_context()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(context.run, asyncio.run, coro)
            # From here the worker thread owns the coroutine: asyncio.run
            # closes it even when the coroutine itself raises.
            submitted = True
            return future.result()
    finally:
        if not submitted:
            coro.close()


__all__ = ["run_sync"]
