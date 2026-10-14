"""Run blocking work without blocking the loop or abandoning file operations."""

import asyncio
from functools import wraps


async def run_blocking(function, *args, **kwargs):
    # Cancelling an asyncio wrapper cannot stop a running thread. Join it before
    # the caller removes files or releases resources used by the operation.
    operation = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        try:
            await operation
        except Exception:
            pass
        raise


def offload(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        return await run_blocking(function, *args, **kwargs)
    return wrapped
