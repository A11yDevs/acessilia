"""Best-effort remote cancellation and its job-status reporting."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from backend.config.settings import settings
from backend.services import operation_registry as registry_module
from backend.services import remote_cancellation
from backend.services.operation_registry import (
    OperationRegistry,
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
        (_Result("cancelled", True), "requested"),
        (_Result("finished"), "finished"),
        (_Result("not_found"), "not_found"),
        (_Result("failed", error="timeout"), "failed"),
    ],
)
def test_cancel_summarizes_each_outcome(monkeypatch, result, expected):
    operation_registry.clear("task-1")
    operation = operation_registry.begin("task-1", "primary")
    client = _Client({operation.operation_id: result})
    monkeypatch.setattr(remote_cancellation, "make_toolbox_client", lambda _cls, _toolbox: client)

    assert asyncio.run(remote_cancellation.cancel_task_operations("task-1")) == expected
    assert client.calls == [operation.operation_id]
    assert client.closed is True
    operation_registry.clear("task-1")


def test_a_failure_is_not_hidden_by_another_operation(monkeypatch):
    """One inconclusive cancel means the remote work may still be running."""
    operation_registry.clear("task-1")
    first = operation_registry.begin("task-1", "upload")
    second = operation_registry.begin("task-1", "primary")
    client = _Client(
        {
            first.operation_id: _Result("cancel_requested", True),
            second.operation_id: _Result("failed", error="timeout"),
        }
    )
    monkeypatch.setattr(remote_cancellation, "make_toolbox_client", lambda _cls, _toolbox: client)

    assert asyncio.run(remote_cancellation.cancel_task_operations("task-1")) == "failed"
    operation_registry.clear("task-1")


def test_a_failed_request_does_not_raise(monkeypatch):
    operation_registry.clear("task-1")
    operation_registry.begin("task-1", "upload")

    class Client(_Client):
        async def cancel(self, operation_id, *, task_id, timeout_seconds):
            raise RuntimeError("connection reset")

    client = Client({})
    monkeypatch.setattr(remote_cancellation, "make_toolbox_client", lambda _cls, _toolbox: client)

    assert asyncio.run(remote_cancellation.cancel_task_operations("task-1")) == "failed"
    assert client.closed is True
    operation_registry.clear("task-1")


def test_a_failing_close_does_not_raise(monkeypatch):
    """The transport cleanup runs inside the budget and never fails the API."""
    operation_registry.clear("task-1")
    operation = operation_registry.begin("task-1", "primary")

    class Client(_Client):
        async def close(self) -> None:
            raise RuntimeError("close failed")

    client = Client({operation.operation_id: _Result("cancel_requested", True)})
    monkeypatch.setattr(remote_cancellation, "make_toolbox_client", lambda _cls, _toolbox: client)

    assert asyncio.run(remote_cancellation.cancel_task_operations("task-1")) == "failed"
    operation_registry.clear("task-1")


def test_a_slow_close_is_cut_by_the_cancel_budget(monkeypatch):
    operation_registry.clear("task-1")
    operation = operation_registry.begin("task-1", "primary")
    monkeypatch.setattr(settings, "toolbox_cancel_timeout_seconds", 0.1)

    class Client(_Client):
        async def close(self) -> None:
            await asyncio.sleep(0.3)
            await super().close()

    client = Client({operation.operation_id: _Result("cancel_requested", True)})
    monkeypatch.setattr(remote_cancellation, "make_toolbox_client", lambda _cls, _toolbox: client)

    started = time.monotonic()
    assert asyncio.run(remote_cancellation.cancel_task_operations("task-1")) == "failed"
    assert time.monotonic() - started < 0.25
    operation_registry.clear("task-1")


def test_cancelled_task_refuses_new_operations():
    operation_registry.clear("task-1")
    operation_registry.cancel_task("task-1")
    with pytest.raises(RemoteOperationCancelled):
        operation_registry.begin("task-1", "primary")
    operation_registry.clear("task-1")


def test_a_cancel_cannot_slip_between_the_check_and_the_registration(monkeypatch):
    """``begin`` checks and inserts in one critical section (review of #527)."""
    registry = OperationRegistry()
    started, release = threading.Event(), threading.Event()
    real_uuid4 = registry_module.uuid.uuid4

    def slow_uuid4():
        started.set()
        assert release.wait(3)
        return real_uuid4()

    monkeypatch.setattr(
        registry_module, "uuid", SimpleNamespace(uuid4=slow_uuid4)
    )
    outcome: list[object] = []

    def worker() -> None:
        try:
            outcome.append(registry.begin("task-race", "primary"))
        except RemoteOperationCancelled as exc:
            outcome.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert started.wait(3)
        # The id is being generated, so ``begin`` has not entered the critical
        # section yet: the cancel must still be visible when it does.
        registry.cancel_task("task-race")
    finally:
        release.set()
        thread.join(5)

    assert thread.is_alive() is False
    assert len(outcome) == 1 and isinstance(outcome[0], RemoteOperationCancelled)
    assert registry.active("task-race") == []
