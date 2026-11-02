"""run_sync works with and without a running event loop."""

from __future__ import annotations

import asyncio

import pytest

from acessilia_sdk.runtime import run_sync


def test_outside_an_event_loop() -> None:
    async def value() -> int:
        return 42

    assert run_sync(value()) == 42


@pytest.mark.asyncio
async def test_inside_a_running_event_loop() -> None:
    """``asyncio.run`` would raise here; ``run_sync`` moves to a worker thread."""

    async def value() -> str:
        await asyncio.sleep(0)
        return "ok"

    assert run_sync(value()) == "ok"
