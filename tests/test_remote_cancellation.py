"""Best-effort remote cancellation and its job-status reporting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from backend.services import remote_cancellation
from backend.services.operation_registry import (
    RemoteOperationCancelled,
    operation_registry,
)


@dataclass
class _Result:
    state: str
    cancel_requested: bool = False
    error: str | None = None


class _Client:
    def __init__(self, results: dict[str, _Result]) -> None:
        self.results = results
        self.calls: list[str] = []
        self.closed = False

    async def cancel(self, operation_id: str, *, task_id: str, timeout_seconds: float):
        assert task_id == "task-1"
        self.calls.append(operation_id)
        return self.results[operation_id]

    async def close(self) -> None:
        self.closed = True


def test_no_active_operation_reports_none():
    operation_registry.clear("task-1")
    assert asyncio.run(remote_cancellation.cancel_task_operations("task-1")) == "none"


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_Result("cancel_requested", True), "requested"),
        (_Result("finished"), "finished"),
        (_Result("not_found"), "not_found"),
        (_Result("failed", error="timeout"), "failed"),
    ],
)
def test_cancel_summarizes_each_outcome(monkeypatch, result, expected):
    operation_registry.clear("task-1")
    operation = operation_registry.begin("task-1", "primary")
    client = _Client({operation.operation_id: result})
    monkeypatch.setattr(remote_cancellation, "make_toolbox_client", lambda _cls: client)

    assert asyncio.run(remote_cancellation.cancel_task_operations("task-1")) == expected
    assert client.calls == [operation.operation_id]
    assert client.closed is True
    operation_registry.clear("task-1")


def test_a_failed_request_does_not_raise(monkeypatch):
    operation_registry.clear("task-1")
    operation_registry.begin("task-1", "upload")

    class Client(_Client):
        async def cancel(self, operation_id, *, task_id, timeout_seconds):
            raise RuntimeError("connection reset")

    client = Client({})
    monkeypatch.setattr(remote_cancellation, "make_toolbox_client", lambda _cls: client)

    assert asyncio.run(remote_cancellation.cancel_task_operations("task-1")) == "failed"
    assert client.closed is True
    operation_registry.clear("task-1")


def test_cancelled_task_refuses_new_operations():
    operation_registry.clear("task-1")
    operation_registry.cancel_task("task-1")
    with pytest.raises(RemoteOperationCancelled):
        operation_registry.begin("task-1", "primary")
    operation_registry.clear("task-1")
