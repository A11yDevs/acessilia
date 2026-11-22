"""Best-effort cancellation of the Toolbox operations owned by a job.

This module never raises: a cancel request that fails is reported to the job
status and logged, so the user's cancel still ends the local job.  The original
``run_blocking`` wait is unchanged (ADR-0019).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from acessilia_core.logger import logger
from acessilia_core.toolbox.toolbox_client import make_toolbox_client
from acessilia_sdk.toolbox import OperationCancelResult, ToolboxOperationClient
from backend.config.core_config import core_config_from_settings
from backend.config.settings import settings
from backend.services.operation_registry import ActiveOperation, operation_registry


async def cancel_task_operations(task_id: str) -> str:
    """Ask the Toolbox to cancel every active operation of ``task_id``.

    Returns one machine-readable state for the job status:
    ``none`` (nothing was active), ``requested`` (at least one cancel was
    accepted), ``finished`` (only operations that had already ended),
    ``not_found`` (every endpoint said it did not know the operations) or
    ``failed`` (a request was inconclusive, failed or the whole batch exceeded
    the short budget).  A failure is never hidden by another operation's
    success.
    """
    operation_registry.cancel_task(task_id)
    active = operation_registry.active(task_id)
    if not active:
        return "none"

    timeout = max(0.1, float(settings.toolbox_cancel_timeout_seconds))
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        client = make_toolbox_client(
            ToolboxOperationClient, core_config_from_settings().toolbox
        )
    except Exception as exc:  # noqa: BLE001 - cancellation must never fail the job
        logger.warning(
            "Toolbox cancellation is not configured for task {}: {}", task_id, exc
        )
        return "failed"
    results: list[OperationCancelResult | BaseException] | None = None
    closed = True
    try:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(
                        client.cancel(
                            operation.operation_id,
                            task_id=task_id,
                            timeout_seconds=timeout,
                        )
                        for operation in active
                    ),
                    return_exceptions=True,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(
                "Toolbox cancellation for task {} exceeded {} s; local cancel continues",
                task_id,
                timeout,
            )
        if results is not None:
            _log_results(task_id, active, results)
    finally:
        # Cleanup shares the same wall-clock budget: a slow or failing close
        # must not turn a user cancel into an API error, nor outlive the
        # configured budget.
        closed = await _close_within_budget(
            client, deadline - asyncio.get_running_loop().time(), task_id
        )
    if results is None or not closed:
        return "failed"
    return _summarize(results)


def _log_results(
    task_id: str,
    active: list[ActiveOperation],
    results: list[OperationCancelResult | BaseException],
) -> None:
    for operation, result in zip(active, results):
        if isinstance(result, BaseException):
            logger.warning(
                "Toolbox cancellation failed for task {} operation {} ({}): {}",
                task_id,
                operation.operation_id,
                operation.kind,
                result,
            )
        elif result.error:
            logger.warning(
                "Toolbox cancellation was not confirmed for task {} operation {} ({}): {}",
                task_id,
                operation.operation_id,
                operation.kind,
                result.error,
            )
        else:
            logger.info(
                "Toolbox cancellation for task {} operation {} ({}): {}",
                task_id,
                operation.operation_id,
                operation.kind,
                result.state,
            )


async def _close_within_budget(
    client: ToolboxOperationClient, budget: float, task_id: str
) -> bool:
    """Close the cancel client inside ``budget``; return whether it closed.

    The caller records ``failed`` when it returns ``False``.  Nothing here ever
    raises: the local cancellation is already persisted and must not fail.
    """
    if budget <= 0:
        logger.warning(
            "No cancel budget left to close the Toolbox client for task {}; "
            "closing it in the background",
            task_id,
        )
        _close_in_background(client, task_id)
        return False
    try:
        await asyncio.wait_for(client.close(), timeout=budget)
    except TimeoutError:
        logger.warning(
            "Closing the Toolbox cancellation client for task {} exceeded {:.2f} s; "
            "closing it in the background",
            task_id,
            budget,
        )
        _close_in_background(client, task_id)
        return False
    except Exception as exc:  # noqa: BLE001 - cancellation must never fail the job
        logger.warning(
            "Closing the Toolbox cancellation client for task {} failed: {}",
            task_id,
            exc,
        )
        return False
    return True


#: Background closes still running. The event loop keeps only a weak
#: reference to a task, so one nobody holds can be collected before it ends.
_BACKGROUND_CLOSES: set[asyncio.Task] = set()


def _close_in_background(client: ToolboxOperationClient, task_id: str) -> None:
    """Release the connections without delaying the API any further."""

    async def close() -> None:
        try:
            await client.close()
        except Exception as exc:  # noqa: BLE001 - nothing left to report it to
            logger.warning(
                "Deferred close of the Toolbox cancellation client for task {} failed: {}",
                task_id,
                exc,
            )

    task = asyncio.create_task(close())
    _BACKGROUND_CLOSES.add(task)
    task.add_done_callback(_BACKGROUND_CLOSES.discard)


def _summarize(
    results: Iterable[OperationCancelResult | BaseException],
) -> str:
    states = [
        None if isinstance(result, BaseException) else result.state
        for result in results
    ]
    # An inconclusive operation may still be running, so it is never hidden by
    # another operation's acknowledgement or finished state.
    if any(state is None or state == "failed" for state in states):
        return "failed"
    if any(state in {"cancel_requested", "cancelled"} for state in states):
        return "requested"
    if states and all(state == "finished" for state in states):
        return "finished"
    if states and all(state == "not_found" for state in states):
        return "not_found"
    return "failed"


__all__ = ["cancel_task_operations"]
