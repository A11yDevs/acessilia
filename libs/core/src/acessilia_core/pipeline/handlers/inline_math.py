"""The document's prose inline math as a planned method (#640, M4b).

Until 0.3.19 the orchestrator marked the prose's inline math before
planning, and again in a pass after execution over the blocks the plan added
(#599). ``inline-math-marker`` runs the step as the method of the document's
``mark-inline-math`` obligation (``docs/architecture/workflow-actions.md``):
``_enrich_inline_math`` finds each run of math in the obligation's prose from
the text layer's fonts and writes it as ``$…$``, and marks again a table
whose marks went stale when the secondary provider's cells were adopted. A
block the plan adds (a ``rescue-omitted`` paragraph) gets its marks on the
replan, through the reconciliation, so the pass after execution is gone.

The formula conversions (``verbalize-formula``, ``normalize-formula``) wait
for this step whatever their targets: they mark implicit products with the
variables the prose's inline math gives. When the step marks a block after
some of them already ran (a replan for an added block), it drops their
conversions, so the canonical build redoes them with the final variables
(``_invalidate_formula_conversions``), as the pass after execution did.

The detection reads the Toolbox's ``document.text.spans`` (an optional call,
#848) through the run's text-span reader (``RunServices``), shared with the
table enrichment. The detection algorithm runs in the core (``docstruct``),
so the method is ``transitional``. With the detection off, or for another
medium, the step changes nothing. The method fails only when the step raises,
or when none of its targets is in the manifest any more.
"""

from __future__ import annotations

from pathlib import Path

from acessilia_core.config import CoreConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.i18n.stage_messages import STAGE_MARKING_INLINE_MATH
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.enrichment.inline_math import (
    _carries_inline_math,
    _enrich_inline_math,
    _invalidate_formula_conversions,
    inline_math_detection_status,
    run_text_spans,
)
from acessilia_core.pipeline.handlers.common import run_status
from acessilia_core.pipeline.handlers.messages import (
    MSG_HANDLER_OBLIGATION_NOT_FOUND,
    MSG_INLINE_MATH_MARKED,
)
from acessilia_core.ports import RunPorts
from acessilia_sdk.runtime import run_sync

#: The formula obligations whose conversions read the prose's variables.
_CONVERSIONS = frozenset({"verbalize-formula", "normalize-formula"})


async def _mark(
    manifest: ProcessingManifest, source: Path, config: CoreConfig, ports: RunPorts, targets: frozenset[str]
) -> dict[str, int]:
    status = run_status(ports)
    if status is not None:
        await status(t(STAGE_MARKING_INLINE_MATH))
    return await _enrich_inline_math(
        manifest, source, config.document, run_text_spans(ports, manifest, source, config.toolbox),
        targets=targets,
    )


def _handle_inline_math_marker_method(
    manifest: ProcessingManifest, obligation_id: str, *, config: CoreConfig, ports: RunPorts
) -> MethodResult:
    """Mark the document's inline math; satisfied once the step ran for its elements."""
    obligation = next((item for item in manifest.obligations if item.id == obligation_id), None)
    targets = frozenset(obligation.target_ids) if obligation is not None else frozenset()
    elements = [element for element in manifest.elements if element.id in targets]
    if not elements:
        return MethodResult(
            success=False, validated=False,
            message=t(MSG_HANDLER_OBLIGATION_NOT_FOUND).format(obligation_id=obligation_id),
        )
    counts = run_sync(_mark(manifest, Path(manifest.source.path), config, ports, targets))
    converted = any(
        item.kind in _CONVERSIONS and item.status == "satisfied" for item in manifest.obligations
    )
    if converted and (counts["marked"] or any(_carries_inline_math(element) for element in elements)):
        # Conversions made before these marks used the old variables.
        _invalidate_formula_conversions(manifest)
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_INLINE_MATH_MARKED, len(elements)).format(
            count=len(elements),
            marked=counts["marked"],
            elements=counts["elements"],
            unmatched=counts["unmatched"],
            detection=inline_math_detection_status(manifest, config.document),
        ),
    )


__all__ = ["_handle_inline_math_marker_method"]
