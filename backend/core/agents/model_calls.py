"""The execution port for synchronous model calls, owned by the application.

Agents accept a runner by composition. A scope supplies the same dependency
to legacy pipeline constructors and across transient event loops; it owns no
threads and reads no settings. A standalone caller supplies its own runner.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol, TypeVar

T = TypeVar("T")


class ModelCallTimeout(TimeoutError):
    """The overall call deadline expired, including admission/worker wait."""


class ModelCallRejected(RuntimeError):
    """Execution capacity is full or the application has closed the runner."""


class ModelCallRunner(Protocol):
    async def run(self, call: Callable[[], T], *, timeout: float, label: str) -> T:
        """Execute one attempt; cancellation never joins an abandoned thread."""


_runner: ContextVar[ModelCallRunner | None] = ContextVar("model_call_runner", default=None)


def current_model_calls() -> ModelCallRunner:
    runner = _runner.get()
    if runner is None:
        raise RuntimeError("A model-call runner must be supplied by the application")
    return runner


@contextmanager
def model_call_scope(runner: ModelCallRunner) -> Iterator[None]:
    token = _runner.set(runner)
    try:
        yield
    finally:
        _runner.reset(token)
