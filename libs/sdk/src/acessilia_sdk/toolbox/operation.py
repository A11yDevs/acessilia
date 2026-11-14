"""Operation identifiers carried by Toolbox HTTP requests.

The caller (the agentic core) owns ``task_id`` and ``operation_id``; the SDK
owns ``attempt_id``.  One logical operation may span retries and endpoint
failover, so the operation id stays stable while each network attempt gets a
new attempt id.  The identifiers travel as headers and are optional: callers
that do not set a context keep the pre-ADR-0019 behaviour.

This module is pure: it reads no settings, environment or global state beyond
a :mod:`contextvars` value scoped to the current async task.  Concurrent jobs
in one process therefore do not share each other's identifiers.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

OPERATION_ID_HEADER = "X-Acessilia-Operation-Id"
TASK_ID_HEADER = "X-Acessilia-Task-Id"
ATTEMPT_ID_HEADER = "X-Acessilia-Attempt-Id"

_CURRENT: ContextVar[OperationContext | None] = ContextVar(
    "acessilia_toolbox_operation", default=None
)


@dataclass(frozen=True)
class OperationContext:
    """Identifiers of one logical remote operation and its current attempt."""

    task_id: str
    operation_id: str
    attempt_id: str | None = None


def new_operation_id() -> str:
    """A fresh, log-safe operation id.  The caller decides when to reuse it."""
    return uuid.uuid4().hex


def new_attempt_id() -> str:
    """A fresh attempt id for one HTTP request, including a retry."""
    return uuid.uuid4().hex


def current_operation() -> OperationContext | None:
    """The operation context of the current async task, if any."""
    return _CURRENT.get()


@contextmanager
def operation_context(
    task_id: str,
    operation_id: str,
    *,
    attempt_id: str | None = None,
) -> Iterator[OperationContext]:
    """Attach identifiers to every Toolbox request made inside the block."""
    if not task_id:
        raise ValueError("task_id must not be empty")
    if not operation_id:
        raise ValueError("operation_id must not be empty")
    context = OperationContext(task_id, operation_id, attempt_id)
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)


@contextmanager
def operation_attempt() -> Iterator[OperationContext | None]:
    """Give the current operation a fresh attempt id for one request.

    A retry or a failover enters this block again, so the same operation id
    reaches the Toolbox with a different attempt id.  Without an operation
    context this is a no-op, keeping identifier-free callers unchanged.
    """
    context = _CURRENT.get()
    if context is None:
        yield None
        return
    token = _CURRENT.set(replace(context, attempt_id=new_attempt_id()))
    try:
        yield _CURRENT.get()
    finally:
        _CURRENT.reset(token)


def operation_headers() -> dict[str, str]:
    """Headers for the current operation, or an empty mapping."""
    context = _CURRENT.get()
    if context is None:
        return {}
    headers = {
        TASK_ID_HEADER: context.task_id,
        OPERATION_ID_HEADER: context.operation_id,
    }
    if context.attempt_id:
        headers[ATTEMPT_ID_HEADER] = context.attempt_id
    return headers


__all__ = [
    "ATTEMPT_ID_HEADER",
    "OPERATION_ID_HEADER",
    "TASK_ID_HEADER",
    "OperationContext",
    "current_operation",
    "new_attempt_id",
    "new_operation_id",
    "operation_attempt",
    "operation_context",
    "operation_headers",
]
