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

    ``asyncio.run`` raises when a loop is already running in this thread; the
    coroutine then runs on a fresh loop in a worker thread instead, inside a
    copy of the caller's :mod:`contextvars` context so operation identifiers
    and other request-scoped variables propagate across the thread boundary.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    context = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(context.run, asyncio.run, coro).result()


__all__ = ["run_sync"]
