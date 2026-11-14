"""The ``vlm-pairwise-judge`` handler: a page judge between the two providers.

It runs the page judge (``backend/core/pipeline/judge.py``) on the pages of
the obligation's targets, with the secondary provider's extraction
(``_secondary_or_failure``), and reports the outcome. Moved verbatim from the
PDDL orchestrator once ADR-0017 was accepted (#402, phase 3, step 6).
"""

from __future__ import annotations

from typing import Any

from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    ProcessingManifest,
)
from backend.core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from backend.core.pipeline.judge import (
    _judge_one_page,
    _judge_texts,
    _judgement_result,
)
from backend.core.pipeline.secondary import (
    _secondary_or_failure,
)


def _handle_vlm_pairwise_judge_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pairwise VLM judge between the two providers' pages.

    The Toolbox (``document.adjudicate.page``) returns the position-debiased
    probability that the secondary page is the more faithful transcription.
    Candidate A is the page the manifest carries and B the other provider's:
    the secondary page, or, on a page the deterministic router already took
    from the secondary provider (its elements carry that ``metadata.provider``),
    the primary elements it replaced. Such a page without the replaced elements
    in the artifact is skipped: comparing it with the secondary page would
    compare MinerU with itself and report a confirmation. Only pages
    where the two transcriptions diverge are judged (``should_judge``). Of
    docstruct's two-threshold rule (``decide_pair``) only the ``p_new >
    DEFAULT_NEW_THR`` branch applies: there is no previous judge to consult
    here. A confirmed page satisfies the obligation; a preferred alternative is
    recorded in ``page_judgement`` but not swapped in (that would reopen the
    manifest mid-plan), so the method fails and the non-critical obligation
    becomes a technical warning. An answer without a valid ``pB`` fails the
    method instead of counting as a confirmation.
    """
    from docstruct.fusion.judge import should_judge

    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    judgements: dict[int, dict[str, Any]] = {}
    for page_number in sorted({e.page_number for e in elements if e.page_number}):
        texts = _judge_texts(manifest, secondary, page_number)
        if texts is None:
            continue
        content, other, primary_md, secondary_md = texts
        if not should_judge(primary_md, secondary_md):
            judgements[page_number] = {
                "content": content, "choice": content, "pB": None, "reason": "agree",
            }
            continue
        judgement, failure = _judge_one_page(
            manifest, page_number, content, other, primary_md, secondary_md
        )
        if failure is not None:
            return failure
        judgements[page_number] = judgement

    return _judgement_result(elements, judgements)
