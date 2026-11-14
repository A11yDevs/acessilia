"""The terminal ``human-review`` method: escalate an obligation to a person.

Moved verbatim from the PDDL orchestrator (#402, phase 3, step 6).
"""

from __future__ import annotations

from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    ProcessingManifest,
)
from backend.core.pipeline.handlers.common import (
    _missing_obligation,
)
from backend.core.pipeline.handlers.messages import MSG_HUMAN_REVIEW
from backend.core.i18n import t


def _handle_human_review_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Record the obligation as escalated to a human reviewer.

    `human-review` is the terminal method every obligation lists as its last
    admissible option. It is not an automated method that can succeed on its own,
    so resolving it must be an explicit decision: an obligation reaching this
    handler is escalated and stays visible in the execution report, instead of
    being marked satisfied by a handler that did nothing.
    """
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)

    return MethodResult(
        success=False,
        validated=False,
        message=t(MSG_HUMAN_REVIEW).format(
            kind=obligation.kind, obligation_id=obligation_id
        ),
    )
