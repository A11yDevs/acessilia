"""Run blocking work without blocking the loop or abandoning file operations.

A core helper, built on the standard library only (ADR-0016, step 4): the
stages and the service both use it, so it is not a port.
"""

import asyncio


async def run_blocking(function, *args, **kwargs):
    # Cancelling an asyncio wrapper cannot stop a running thread. Join it before
    # the caller removes files or releases resources used by the operation.
    operation = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not operation.cancelled():
            operation.exception()
        raise


__all__ = ["run_blocking"]
