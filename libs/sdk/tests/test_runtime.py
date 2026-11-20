"""run_sync works with and without a running event loop and preserves contextvars."""

from __future__ import annotations

import asyncio
import contextvars

import pytest
from acessilia_sdk.runtime import run_sync
from acessilia_sdk.toolbox.operation import current_operation, operation_context

_REQUEST_TAG: contextvars.ContextVar[str] = contextvars.ContextVar(
    "test_runtime_request_tag", default="unset"
)


def test_outside_an_event_loop() -> None:
    async def value() -> int:
        return 42

    assert run_sync(value()) == 42


def test_preserves_contextvars_outside_an_event_loop() -> None:
    token = _REQUEST_TAG.set("outer-sync")
    try:
        async def read_and_mutate() -> str:
            seen = _REQUEST_TAG.get()
            _REQUEST_TAG.set("mutated-in-coro")
            return seen

        assert run_sync(read_and_mutate()) == "outer-sync"
        assert _REQUEST_TAG.get() == "outer-sync"
    finally:
        _REQUEST_TAG.reset(token)


@pytest.mark.asyncio
async def test_inside_a_running_event_loop() -> None:
    """``asyncio.run`` would raise here; ``run_sync`` moves to a worker thread."""

    async def value() -> str:
        await asyncio.sleep(0)
        return "ok"

    assert run_sync(value()) == "ok"


@pytest.mark.asyncio
async def test_preserves_contextvars_and_operation_context_inside_running_loop() -> None:
    token = _REQUEST_TAG.set("req-123")
    try:
        with operation_context(task_id="task-9", operation_id="op-7"):
            async def inspect_context() -> tuple[str, str | None, str | None]:
                await asyncio.sleep(0)
                seen_tag = _REQUEST_TAG.get()
                _REQUEST_TAG.set("worker-only")
                op = current_operation()
                return (
                    seen_tag,
                    op.task_id if op else None,
                    op.operation_id if op else None,
                )

            assert run_sync(inspect_context()) == ("req-123", "task-9", "op-7")
            # Worker-thread mutations must not leak back to the caller's context.
            assert _REQUEST_TAG.get() == "req-123"
    finally:
        _REQUEST_TAG.reset(token)
