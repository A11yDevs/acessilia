"""Fixtures shared by the core library tests."""

from __future__ import annotations

import asyncio
import contextvars
import math
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

import pytest

from acessilia_core.agents.model_calls import (
    ModelCallRunner,
    ModelCallTimeout,
    model_call_scope,
)

T = TypeVar("T")


class TestModelCallRunner(ModelCallRunner):
    """Simple test runner executing model calls in a thread pool."""

    def __init__(self, workers: int = 4) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers)

    async def run(self, call: Callable[[], T], *, timeout: float, label: str) -> T:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("A model call requires a finite nonnegative timeout")
        loop = asyncio.get_running_loop()
        # Match the service runner: the worker sees the caller's context, so
        # request-scoped values such as the locale survive the thread hop.
        future = loop.run_in_executor(self._pool, contextvars.copy_context().run, call)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ModelCallTimeout(f"{label} timed out") from exc

    def close(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


@pytest.fixture(autouse=True)
def model_calls() -> Iterator[TestModelCallRunner]:
    """Ensure a model call runner is in scope for any test exercising agents."""
    runner = TestModelCallRunner(workers=4)
    try:
        with model_call_scope(runner):
            yield runner
    finally:
        runner.close(wait=True)


@pytest.fixture(autouse=True)
def _locales_start_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts from unconfigured locales."""
    from acessilia_core import i18n

    monkeypatch.setattr(i18n, "_SERVER_LOCALE", None)
    monkeypatch.setattr(i18n, "_ACTIVE_LOCALES", None)
