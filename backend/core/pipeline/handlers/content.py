"""Deterministic handlers that check or finish an element's content.

Picture descriptions and table structure are produced before planning, by the
enrichment stages; their handlers verify that the work happened instead of
pretending to do it. Code blocks are normalized in place. Moved verbatim from
the PDDL orchestrator (#402, phase 3, step 6).
"""

from __future__ import annotations

from docstruct.placeholders import has_meaningful_text
from docstruct.tables.ast import (
    linearize_table_for_text,
    raw_rows_from_table_ast as _rows_from_table_ast,
)
from docstruct.text.code_reflow import normalize_code_text

from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    ProcessingManifest,
)
from backend.core.pipeline.elements import (
    _table_element_has_structured_content,
)
from backend.core.pipeline.handlers.common import (
    _target_elements,
)
from backend.core.pipeline.handlers.messages import (
    MSG_CODE_NO_CODE,
    MSG_CODE_NORMALIZED,
    MSG_CODE_NORMALIZED_PARTIAL,
    MSG_TABLE_NO_STRUCTURE,
    MSG_TABLE_NO_TABLE,
    MSG_TABLE_VALIDATED,
    MSG_VISION_NO_PICTURE,
    MSG_VISION_UNDESCRIBED,
    MSG_VISION_VALIDATED,
)
from backend.i18n import n, t


def _handle_vision_description_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require every picture target to already carry a description.

    The description itself is produced before planning (`_enrich_picture_descriptions`
    asks the vision model), so this method validates that the work the planner is
    asking for actually happened instead of pretending to perform it. A picture
    that is still undescribed is a real failure and keeps the next admissible
    method available; `describe-image` is non-critical, so it does not fail the job.
    """
    elements = [
        el
        for el in _target_elements(manifest, obligation_id)
        if el.type == "picture"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_VISION_NO_PICTURE),
        )

    undescribed = [
        el for el in elements
        if not (
            bool((el.text or "").strip())
            if el.metadata.get("vision_description_complete")
            else has_meaningful_text(el)
        )
    ]
    if undescribed:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_VISION_UNDESCRIBED).format(
                ids=", ".join(
                    f"{el.id} ({reason})"
                    if (reason := el.metadata.get("vision_failure_reason"))
                    else el.id
                    for el in undescribed
                )
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_VISION_VALIDATED, len(elements)).format(
            count=len(elements)
        ),
    )


def _handle_pandoc_table_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require the table targets to carry a structured AST."""
    elements = [
        el for el in _target_elements(manifest, obligation_id) if el.type == "table"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_TABLE_NO_TABLE),
        )

    missing = []
    for element in elements:
        try:
            usable = _table_element_has_structured_content(element)
            table_ast = element.metadata.get("table_ast")
            if usable:
                usable = any(
                    value.strip() for row in _rows_from_table_ast(table_ast) for value in row
                )
                # Called only to validate: it raises on an AST the exporters
                # cannot linearize, which makes the table unusable below.
                linearize_table_for_text({"table_ast": table_ast})
        except (TypeError, ValueError, AttributeError):
            usable = False
        if not usable:
            missing.append(element)
    if missing:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_TABLE_NO_STRUCTURE).format(
                ids=", ".join(el.id for el in missing)
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_TABLE_VALIDATED, len(elements)).format(
            count=len(elements)
        ),
    )


def _handle_pandoc_code_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Normalize code targets in place and report how many blocks were changed.

    The normalized text is the evidence: ``MethodResult`` carries the count and
    nothing needs a per-element marker, since the manifest records the method
    attempt that satisfied the obligation.
    """
    elements = [
        el for el in _target_elements(manifest, obligation_id) if el.type == "code"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_CODE_NO_CODE),
        )

    normalized = 0
    for element in elements:
        text = normalize_code_text(element.text or "")
        if not text:
            continue
        element.text = text
        normalized += 1

    if normalized != len(elements):
        return MethodResult(
            success=False,
            validated=False,
            message=n(
                *MSG_CODE_NORMALIZED_PARTIAL, len(elements)
            ).format(done=normalized, total=len(elements)),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_CODE_NORMALIZED, normalized).format(count=normalized),
    )
