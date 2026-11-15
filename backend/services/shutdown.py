"""Process-wide signal that the API is shutting down gracefully (#407).

A shutdown is not a job cancellation. The queue worker stops every active
callback, but a job interrupted that way must keep its durable record, upload,
checkpoints and operation ids so the next startup can resume it. The lifespan
calls :func:`begin_shutdown` before it cancels the queue; the job runner and the
pipeline read :func:`shutting_down` to skip the cleanup that a user cancel
performs.
"""

from __future__ import annotations

import threading

_shutting_down = threading.Event()


def begin_shutdown() -> None:
    """Mark the process as shutting down, before any worker is cancelled."""
    _shutting_down.set()


def shutting_down() -> bool:
    """Whether the process is shutting down and must preserve resumable work."""
    return _shutting_down.is_set()


def reset() -> None:
    """Clear the signal; for tests that simulate one shutdown in a process."""
    _shutting_down.clear()


__all__ = ["begin_shutdown", "reset", "shutting_down"]
