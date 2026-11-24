"""Progress a run reports from the executor's worker thread (#402, #640).

``_plan_progress`` reports each plan step with its pages; ``_thread_status``
lets any work on that thread, such as the ``table-enrichment`` method, report
through the same status callback (``RunServices.progress``). Moved from the
PDDL orchestrator so it stays under the module size limit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from acessilia_core.execution.executor import StepProgress
from acessilia_core.i18n import t
from acessilia_core.i18n.stage_messages import STAGE_EXECUTING_PLAN_STEP
from acessilia_core.logger import logger
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.obligations import _pages_label
from acessilia_core.planning.models import PlanStep


def _plan_progress(
    manifest: ProcessingManifest,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
    loop: asyncio.AbstractEventLoop,
) -> StepProgress | None:
    """Report each obligation step, with its pages, through ``status_callback``.

    The executor runs on a worker thread while the callback is a coroutine of
    the event loop, so the report is scheduled on ``loop`` and awaited from the
    thread: the step only starts once its stage is recorded, which is what lets
    a job killed mid-step still say which step and page it was on. A failing
    report, including a broken translation of the label, is logged and never
    fails the step.

    The user sees only the step and its pages; the obligation kind and method
    are internal names, so they go to the debug log.
    """
    send = _thread_status(status_callback, loop)
    if send is None:
        return None
    page_by_element = {element.id: element.page_number for element in manifest.elements}
    pages_by_obligation = {
        obligation.id: [page_by_element.get(target) for target in obligation.target_ids]
        for obligation in manifest.obligations
    }

    def report(step: PlanStep, position: int, total: int) -> None:
        if step.action != "execute-obligation" or step.obligation_id is None:
            return
        pages = pages_by_obligation.get(step.obligation_id, [])
        logger.debug(
            "PDDL: step {}/{} {} via {}, pages {}",
            position,
            total,
            step.obligation_id,
            step.method,
            pages,
        )
        try:
            message = t(STAGE_EXECUTING_PLAN_STEP).format(
                current=position,
                total=total,
                pages=_pages_label(pages, len(manifest.pages)),
            )
        except Exception as exc:  # noqa: BLE001 - progress must not fail the plan
            logger.warning("PDDL: progress of step {} not recorded: {}", position, exc)
            return
        send(message)

    return report


def _thread_status(
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
    loop: asyncio.AbstractEventLoop,
) -> Callable[[str], None] | None:
    """Report a progress message from a worker thread through ``status_callback``.

    The callback is a coroutine of ``loop``: the report is scheduled there and
    awaited from the thread, so the work only goes on once its stage is
    recorded. A failing report is logged and never fails the work.
    """
    if status_callback is None:
        return None

    def send(message: str) -> None:
        try:
            asyncio.run_coroutine_threadsafe(status_callback(message), loop).result(
                timeout=_PROGRESS_REPORT_TIMEOUT_SECONDS
            )
        except Exception as exc:  # noqa: BLE001 - progress must not fail the work
            logger.warning("PDDL: progress not recorded: {}", exc)

    return send


#: Upper bound on how long a plan step waits for its progress to be recorded.
_PROGRESS_REPORT_TIMEOUT_SECONDS = 10.0
