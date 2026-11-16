"""Offload the service's blocking functions to a thread."""

from functools import wraps

from backend.core.blocking import run_blocking


def offload(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        return await run_blocking(function, *args, **kwargs)
    return wrapped


__all__ = ["offload"]
