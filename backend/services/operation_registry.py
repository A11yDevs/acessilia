"""Process-local registry of remote operations owned by a running job.

ADR-0019 keeps the operation journal in memory for the life of the job.  The
core only needs it to find operations to cancel; a Toolbox restart, an
independent endpoint or a core restart loses the association, in which case a
cancel reports it could not reach the operation.  Durable resumption is #407.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Literal

OperationKind = Literal["upload", "primary", "secondary"]


class RemoteOperationCancelled(Exception):
    """A new remote operation was refused because its job is being cancelled."""


@dataclass(frozen=True)
class ActiveOperation:
    task_id: str
    operation_id: str
    kind: OperationKind
    started_at: float


class OperationRegistry:
    """Thread-safe map of task id to its currently running operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_task: dict[str, dict[str, ActiveOperation]] = {}
        self._cancelled_tasks: set[str] = set()

    def begin(self, task_id: str, kind: OperationKind) -> ActiveOperation:
        with self._lock:
            if task_id in self._cancelled_tasks:
                raise RemoteOperationCancelled(task_id)
        operation = ActiveOperation(
            task_id=task_id,
            operation_id=uuid.uuid4().hex,
            kind=kind,
            started_at=time.time(),
        )
        with self._lock:
            self._by_task.setdefault(task_id, {})[operation.operation_id] = operation
        return operation

    def finish(self, task_id: str, operation_id: str) -> None:
        with self._lock:
            operations = self._by_task.get(task_id)
            if operations is None:
                return
            operations.pop(operation_id, None)
            if not operations:
                self._by_task.pop(task_id, None)

    def active(self, task_id: str) -> list[ActiveOperation]:
        with self._lock:
            return list(self._by_task.get(task_id, {}).values())

    def cancel_task(self, task_id: str) -> None:
        """Refuse new operations and mark the task as cancellation-requested."""
        with self._lock:
            self._cancelled_tasks.add(task_id)

    def clear(self, task_id: str) -> None:
        with self._lock:
            self._by_task.pop(task_id, None)
            self._cancelled_tasks.discard(task_id)


operation_registry = OperationRegistry()

__all__ = [
    "ActiveOperation",
    "OperationKind",
    "OperationRegistry",
    "RemoteOperationCancelled",
    "operation_registry",
]
