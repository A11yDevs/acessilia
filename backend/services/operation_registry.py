"""Process-local registry of remote operations owned by a running job.

ADR-0019 names every logical remote call and lets the Toolbox join an
``operation_id`` it already knows. This registry finds the operations a job
must cancel; the durable part of the identity lives in
:mod:`backend.services.operation_journal`, so a call repeated after a core
restart reaches the Toolbox under the same id instead of starting a new
provider execution (#407).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, replace

from acessilia_core.ports import OperationKind

from backend.services import operation_journal


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
        """Register one logical call, reusing the id this job already used for it.

        The id is read from the durable journal before the critical section; the
        cancellation check and the insertion then happen together, so a cancel
        cannot slip between them and leave an operation nobody asked to stop.
        """
        operation = ActiveOperation(
            task_id=task_id,
            operation_id=operation_journal.operation_id(task_id, kind)
            or uuid.uuid4().hex,
            kind=kind,
            started_at=time.time(),
        )
        with self._lock:
            if task_id in self._cancelled_tasks:
                raise RemoteOperationCancelled(task_id)
            operations = self._by_task.setdefault(task_id, {})
            if operation.operation_id in operations:
                # The same slot is already running here. Never let two active
                # entries share an id: ``finish`` of one would hide the other.
                operation = replace(operation, operation_id=uuid.uuid4().hex)
            operations[operation.operation_id] = operation
        operation_journal.record(task_id, kind, operation.operation_id)
        return operation

    def finish(self, task_id: str, operation_id: str) -> None:
        with self._lock:
            operations = self._by_task.get(task_id)
            if operations is None:
                return
            operations.pop(operation_id, None)
            if not operations:
                self._by_task.pop(task_id, None)
        operation_journal.set_state(task_id, operation_id, "finished")

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
        operation_journal.forget(task_id)


operation_registry = OperationRegistry()


class JobOperations:
    """The core's ``RemoteOperations`` port for one job, on this process's
    registry (ADR-0016, step 4)."""

    def __init__(self, job_id: str, registry: OperationRegistry = operation_registry) -> None:
        self.job_id = job_id
        self._registry = registry

    def begin(self, kind: OperationKind) -> str:
        return self._registry.begin(self.job_id, kind).operation_id

    def finish(self, operation_id: str) -> None:
        self._registry.finish(self.job_id, operation_id)

__all__ = [
    "ActiveOperation",
    "JobOperations",
    "OperationRegistry",
    "RemoteOperationCancelled",
    "operation_registry",
]
