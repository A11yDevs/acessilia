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
    """Execution capacity is full: local admission pressure, not provider health.

    Callers must not count it against a provider breaker, and may retry it once
    as they do a timeout. A closed runner uses the ``ModelCallClosed`` subtype.
    """


class ModelCallClosed(ModelCallRejected):
    """The application closed the runner: lifecycle, not capacity pressure.

    A closed runner rejects every new call and wakes pending/active awaiters.
    This subtype lets callers separate the shutdown path from a transient
    admission rejection: it is not retried and not recorded as a retryable
    object degradation (#590 review).
    """


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
