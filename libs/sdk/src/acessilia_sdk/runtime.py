"""Bridging asynchronous SDK calls into synchronous code."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import inspect
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def _close_if_never_started(coro: Coroutine[Any, Any, T]) -> None:
    """Close ``coro`` if no event loop took ownership, so it cannot warn at GC.

    ``asyncio.run`` closes a coroutine it started, but it may fail before its
    loop exists (a broken event loop policy, resource exhaustion).  Only a
    native coroutine -- one produced by ``async def`` -- exposes
    ``CORO_CREATED``; custom ``collections.abc.Coroutine`` objects are left to
    their owner, since they cannot emit the native "never awaited" warning and
    their state is not observable.
    """
    if (
        inspect.iscoroutine(coro)
        and inspect.getcoroutinestate(coro) == inspect.CORO_CREATED
    ):
        coro.close()


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
        ``run_sync`` consumes the coroutine object.  If it fails before an
        event loop takes ownership -- ``asyncio.run`` cannot start its loop,
        or the worker setup fails -- a native coroutine (one produced by
        ``async def``) is closed before the error propagates, so the failure
        cannot surface later as ``RuntimeWarning: coroutine ... was never
        awaited``. Custom ``collections.abc.Coroutine`` objects are left to
        their owner.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(coro)
        except BaseException:
            _close_if_never_started(coro)
            raise

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
            _close_if_never_started(coro)


__all__ = ["run_sync"]
