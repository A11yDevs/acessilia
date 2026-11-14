"""Best-effort cancellation of the Toolbox operations owned by a job.

This module never raises: a cancel request that fails is reported to the job
status and logged, so the user's cancel still ends the local job.  The original
``run_blocking`` wait is unchanged (ADR-0019).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from acessilia_sdk.toolbox import OperationCancelResult, ToolboxOperationClient

from backend.config.settings import settings
from backend.services.operation_registry import operation_registry
from backend.tools.logger import logger
from backend.tools.toolbox_client import make_toolbox_client


async def cancel_task_operations(task_id: str) -> str:
    """Ask the Toolbox to cancel every active operation of ``task_id``.

    Returns one machine-readable state for the job status:
    ``none`` (nothing was active), ``requested`` (at least one cancel was
    accepted), ``finished`` (only operations that had already ended),
    ``not_found`` (no endpoint knew an operation) or ``failed`` (a request
    failed or the whole batch exceeded the short budget).
    """
    operation_registry.cancel_task(task_id)
    active = operation_registry.active(task_id)
    if not active:
        return "none"

    timeout = max(0.1, float(settings.toolbox_cancel_timeout_seconds))
    try:
        client = make_toolbox_client(ToolboxOperationClient)
    except Exception as exc:  # noqa: BLE001 - cancellation must never fail the job
        logger.warning(
            "Toolbox cancellation is not configured for task {}: {}", task_id, exc
        )
        return "failed"
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
            return "failed"
    finally:
        await client.close()

    state = _summarize(results)
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
    return state


def _summarize(
    results: Iterable[OperationCancelResult | BaseException],
) -> str:
    states = [
        None if isinstance(result, BaseException) else result.state
        for result in results
    ]
    if any(state == "cancel_requested" for state in states):
        return "requested"
    if states and all(state in {"finished", "cancelled"} for state in states):
        return "finished"
    if any(state == "failed" or state is None for state in states):
        return "failed"
    if states and all(state == "not_found" for state in states):
        return "not_found"
    return "failed"


__all__ = ["cancel_task_operations"]
