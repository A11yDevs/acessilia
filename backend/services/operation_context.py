"""The job id visible to code running inside a job's worker thread."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_TASK_ID: ContextVar[str | None] = ContextVar("acessilia_job_task_id", default=None)


@contextmanager
def task_context(task_id: str | None) -> Iterator[None]:
    """Make ``task_id`` visible to Toolbox calls made inside this block."""
    if not task_id:
        yield
        return
    token = _TASK_ID.set(task_id)
    try:
        yield
    finally:
        _TASK_ID.reset(token)


def current_task_id() -> str | None:
    """The current job id, or ``None`` outside a job."""
    return _TASK_ID.get()


__all__ = ["current_task_id", "task_context"]
