"""Process-owned model execution with bounded, removable pending work.

Only worker reservations are submitted to ThreadPoolExecutor. Pending calls
stay in our bounded OrderedDict, so cancellation removes their closures at
once rather than leaving unbounded cancelled items in the executor's queue.
Running abandoned calls retain capacity until their thread exits. No event
loop owns this executor; asyncio.run() never joins it on loop shutdown.

close(wait=False) rejects new work, discards pending calls and wakes active
awaiters with ModelCallRejected. Active provider threads continue; their late
results are discarded and their reservations remain held until they finish.
Closing cannot kill threads or guarantee immediate interpreter exit. Python
still joins executor threads at exit. The service must be stopped externally if a provider never
returns. A closed process owner is replaced only after its workers finish.
"""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import math
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, TypeVar

from acessilia_core.agents.model_calls import ModelCallRejected, ModelCallTimeout
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    LOG_MODEL_CALL_ABANDONED,
    LOG_MODEL_CALL_EXPIRED,
    LOG_MODEL_CALL_REJECTED,
    LOG_MODEL_CALL_STATE,
    MSG_MODEL_CALL_CLOSED,
    MSG_MODEL_CALL_DEADLINE,
    MSG_MODEL_CALL_FULL,
)
from acessilia_core.logger import logger

T = TypeVar("T")


@dataclass(frozen=True)
class ModelCallLimits:
    workers: int
    max_pending: int

    def __post_init__(self):
        if self.workers < 1 or self.max_pending < 0:
            raise ValueError("Model-call workers must be positive and pending capacity nonnegative")


@dataclass
class _Call:
    call: Callable[[], Any] | None
    context: contextvars.Context
    deadline: float
    label: str
    submitted: float = field(default_factory=time.monotonic)
    result: Future = field(default_factory=Future)
    started: float | None = None
    abandoned: bool = False
    expired: bool = False


class ModelCallExecutor:
    def __init__(self, limits: ModelCallLimits):
        self.limits = limits
        self._pool = ThreadPoolExecutor(max_workers=limits.workers, thread_name_prefix="model-call")
        self._lock = RLock()
        self._active: dict[int, _Call] = {}
        self._pending: OrderedDict[int, _Call] = OrderedDict()
        self._closed = False
        self._rejections = 0
        self._expirations = 0

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "active": len(self._active), "pending": len(self._pending),
                "abandoned": sum(c.abandoned for c in self._active.values()),
                "rejections": self._rejections, "expirations": self._expirations,
                "closed": self._closed,
            }

    def _log(self, message: str, label: str, *, warning=False, **fields):
        values = self.snapshot()
        values.update(fields, label=label)
        (logger.warning if warning else logger.debug)(t(message).format(**values))

    async def run(self, call: Callable[[], T], *, timeout: float, label: str) -> T:
        # Absolute monotonic time also lets a worker refuse an expired call
        # when its caller's event loop is delayed and has not processed a timer.
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("A model call requires a finite nonnegative timeout")
        submitted = time.monotonic()
        entry = _Call(call, contextvars.copy_context(), submitted + timeout, label, submitted=submitted)
        rejected = None
        with self._lock:
            if self._closed or (
                len(self._active) >= self.limits.workers
                and len(self._pending) >= self.limits.max_pending
            ):
                self._rejections += 1
                rejected = MSG_MODEL_CALL_CLOSED if self._closed else MSG_MODEL_CALL_FULL
            elif len(self._active) < self.limits.workers:
                self._dispatch(entry)
            else:
                self._pending[id(entry)] = entry
        if rejected is not None:
            self._log(LOG_MODEL_CALL_REJECTED, label, warning=True)
            raise ModelCallRejected(t(rejected))
        wrapped = asyncio.wrap_future(entry.result)
        # An awaiter can disappear just as a provider fails. Consume a late
        # exception even in that race; it must never publish an abandoned result.
        wrapped.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        timer = asyncio.timeout(max(0, entry.deadline - time.monotonic()))
        try:
            async with timer:
                return await asyncio.shield(wrapped)
        except TimeoutError:
            if not timer.expired():
                raise  # The provider's TimeoutError keeps its original cause.
            self._abandon(entry, expired=True)
            raise ModelCallTimeout(t(MSG_MODEL_CALL_DEADLINE).format(seconds=timeout)) from None
        except asyncio.CancelledError:
            self._abandon(entry, expired=False)
            raise

    def _dispatch(self, entry: _Call):
        self._active[id(entry)] = entry
        try:
            # Never expose this future to asyncio cancellation. The reservation
            # is released by _invoke, including a cancelled pre-start wrapper.
            self._pool.submit(entry.context.run, self._invoke, entry)
        except BaseException:
            self._active.pop(id(entry), None)
            entry.call = None
            raise

    def _invoke(self, entry: _Call):
        expired = False
        completed = False
        value = None
        failure = None
        try:
            with self._lock:
                if entry.abandoned or self._closed:
                    return
                if time.monotonic() >= entry.deadline:
                    expired = self._expire(entry)
                else:
                    entry.started = time.monotonic()
                    call = entry.call
            if entry.started is None:
                if expired:
                    self._log_expired(entry)
                return
            self._log(LOG_MODEL_CALL_STATE, entry.label, event="started",
                      queue_wait=entry.started - entry.submitted, execution=0)
            try:
                value = call()
            except BaseException as error:
                # A worker is an exception-transfer boundary, like
                # concurrent.futures: even SystemExit/CancelledError must reach
                # the awaiter. Otherwise its result stays unresolved until the
                # deadline. This does not suppress the provider's exception.
                failure = error
            completed = True
        finally:
            expired_pending = []
            with self._lock:
                entry.call = None
                self._active.pop(id(entry), None)
                while self._pending and not self._closed and len(self._active) < self.limits.workers:
                    _, pending = self._pending.popitem(last=False)
                    if time.monotonic() >= pending.deadline:
                        if self._expire(pending):
                            expired_pending.append(pending)
                        pending.call = None
                    else:
                        self._dispatch(pending)
                # Publish only after releasing the completed reservation, so
                # a caller can immediately submit its next attempt, even with
                # a zero pending budget. Abandoned results stay cancelled.
                if completed and not entry.result.done():
                    if failure is not None:
                        entry.result.set_exception(failure)
                    else:
                        entry.result.set_result(value)
            self._log(LOG_MODEL_CALL_STATE, entry.label, event="finished",
                      queue_wait=(entry.started or time.monotonic()) - entry.submitted,
                      execution=time.monotonic() - entry.started if entry.started else 0)
            for pending in expired_pending:
                self._log_expired(pending)

    def _expire(self, entry: _Call):
        changed = not entry.expired
        if not entry.expired:
            entry.expired = True
            self._expirations += 1
        if not entry.result.done():
            entry.result.set_exception(ModelCallTimeout(t(MSG_MODEL_CALL_DEADLINE).format(
                seconds=entry.deadline - entry.submitted)))
        return changed

    def _log_expired(self, entry: _Call):
        self._log(LOG_MODEL_CALL_EXPIRED, entry.label, warning=True,
                  queue_wait=(entry.started or time.monotonic()) - entry.submitted)

    def _abandon(self, entry: _Call, *, expired: bool):
        changed = False
        with self._lock:
            entry.abandoned = True
            if self._pending.pop(id(entry), None) is not None:
                entry.call = None
            if expired:
                # Cancel the result first: the awaiter already received the
                # timeout and must not acquire an unobserved exception.
                entry.result.cancel()
                changed = self._expire(entry)
            else:
                entry.result.cancel()
        if changed:
            self._log_expired(entry)
        self._log(LOG_MODEL_CALL_ABANDONED, entry.label, warning=True)

    def close(self, *, wait: bool = False):
        abandoned = []
        with self._lock:
            self._closed = True
            for entry in list(self._pending.values()):
                entry.call = None
                entry.abandoned = True
                entry.result.set_exception(ModelCallRejected(t(MSG_MODEL_CALL_CLOSED)))
            self._pending.clear()
            for entry in self._active.values():
                if not entry.abandoned:
                    abandoned.append(entry)
                entry.abandoned = True
                if not entry.result.done():
                    entry.result.set_exception(ModelCallRejected(t(MSG_MODEL_CALL_CLOSED)))
        for entry in abandoned:
            self._log(LOG_MODEL_CALL_ABANDONED, entry.label, warning=True)
        self._pool.shutdown(wait=wait)


_owner: ModelCallExecutor | None = None
_owner_lock = RLock()


def get_model_calls() -> ModelCallExecutor:
    """The application owner; read capacity settings only when starting it."""
    global _owner
    with _owner_lock:
        if _owner is None or (_owner.snapshot()["closed"] and not _owner.snapshot()["active"]):
            from backend.config.settings import settings
            _owner = ModelCallExecutor(ModelCallLimits(settings.model_call_workers, settings.model_call_max_pending))
        return _owner


def shutdown_model_calls():
    with _owner_lock:
        if _owner is not None:
            _owner.close(wait=False)


atexit.register(shutdown_model_calls)
