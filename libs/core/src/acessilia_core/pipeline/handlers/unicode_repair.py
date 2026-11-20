"""Legacy Unicode and detached negation-overlay repair handler.

Extracted from ``acessilia_core.pipeline.handlers.text`` (#612) to keep each
handler module focused and well below the module size limit. This module is
the canonical owner of the Unicode repair handler and its internal helpers;
``handlers/text.py`` re-exports the entry points for import compatibility.
"""

from __future__ import annotations

from typing import Any

from docstruct.geometry.boxes import downward_edges
from docstruct.tables.ast import TABLE_SECTIONS
from docstruct.text.latex import has_latex_markup
from docstruct.text.negation_overlay import (
    compose_in_grid,
    compose_in_text,
    is_detached_overlay,
)
from docstruct.text.unicode_repair import (
    Detection,
    UnicodeRepairContext,
    detect_legacy_unicode,
    repair_legacy_unicode,
)

from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.logger import logger
from acessilia_core.manifest.detectors import unicode_repair_text
from acessilia_core.manifest.models import ManifestElement, ProcessingManifest
from acessilia_core.pipeline.elements import _OVERLAY_HOST_TOLERANCE, _bbox
from acessilia_core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from acessilia_core.pipeline.handlers.messages import (
    MSG_UNICODE_REPAIR_APPLIED,
    MSG_UNICODE_REPAIR_NO_TEXT,
)

#: Manifest element type -> block type accepted by the Unicode repair. Types
#: absent here (formula, code, table, picture) are never rewritten.
_UNICODE_REPAIR_BLOCK_TYPES = {
    "paragraph": "prose",
    "heading": "heading",
    "title": "heading",
    "list_item": "prose",
    "caption": "prose",
    "footnote": "prose",
    "page_header": "prose",
    "page_footer": "prose",
}


#: Word-internal spaced accents needed before standalone ones (an accent
#: separated from its word) are treated as the same extraction defect. A
#: document that merely mentions an accent has none of the word-internal shape,
#: so it keeps its text; a legacy TeX extraction has hundreds.
_UNICODE_STANDALONE_SPACING_MIN = 5


def _repair_table_cells(
    element: ManifestElement, context: UnicodeRepairContext
) -> tuple[bool, set[str], int, bool]:
    """Repair a table caption and every cell in place.

    Returns ``(edited, rules, edits, needs_review)``. The table keeps its
    structure; only the text of the caption and of the cells changes.
    """
    table_ast = element.metadata.get("table_ast")
    if not isinstance(table_ast, dict):
        return False, set(), 0, False

    edited = False
    rules: set[str] = set()
    edits = 0
    review = False

    def repair_text(current: str) -> str:
        nonlocal edited, edits, review
        decision = repair_legacy_unicode(current, context=context)
        if decision.repaired != current:
            edited = True
        rules.update(edit.rule for edit in decision.edits)
        edits += len(decision.edits)
        review = review or decision.needs_review
        return decision.repaired

    caption = table_ast.get("caption")
    if isinstance(caption, str) and caption:
        table_ast["caption"] = repair_text(caption)
    for section_name in TABLE_SECTIONS:
        section = table_ast.get(section_name)
        if not isinstance(section, list):
            continue
        for row in section:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                text = cell.get("text")
                if isinstance(text, str) and text:
                    cell["text"] = repair_text(text)
    return edited, rules, edits, review


def _compose_in_host(
    host: ManifestElement,
    x_fraction: float,
    y_fraction: float,
    height: float,
    slash_height: float,
) -> str:
    """Negate the relation under the slash in ``host``; returns the outcome.

    The composition is docstruct's (``compose_in_grid`` for a table,
    ``compose_in_text`` otherwise); a formula whose text is already LaTeX is
    not touched (``host-is-latex``).
    """
    if host.type == "table":
        return compose_in_grid(host.metadata.get("table_ast"), x_fraction, y_fraction)
    if host.type == "formula" and has_latex_markup(host.text):
        return "host-is-latex"
    outcome, text = compose_in_text(
        host.text or "", x_fraction, y_fraction, height, slash_height
    )
    if text is not None:
        host.text = text
    return outcome


def _find_overlay_hosts(
    manifest: ProcessingManifest,
    overlay: ManifestElement,
    *,
    page: int,
    x: float,
    y: float,
) -> list[tuple[ManifestElement, Any, float, float]]:
    hosts: list[tuple[ManifestElement, Any, float, float]] = []
    for element in manifest.elements:
        if element is overlay or is_detached_overlay(element.text):
            continue
        other = _bbox(element, page)
        if other is None:
            continue
        top, bottom = downward_edges(other[1])
        if (
            other[1].left - _OVERLAY_HOST_TOLERANCE
            <= x
            <= other[1].right + _OVERLAY_HOST_TOLERANCE
            and top - _OVERLAY_HOST_TOLERANCE <= y <= bottom + _OVERLAY_HOST_TOLERANCE
        ):
            hosts.append((element, other[1], top, bottom))
    return hosts


def _resolve_single_overlay(
    manifest: ProcessingManifest, overlay: ManifestElement
) -> tuple[str, str | None]:
    located = _bbox(overlay)
    if located is None:
        return "no-host", None
    page, box = located
    x = (box.left + box.right) / 2
    upper, lower = downward_edges(box)
    y = (upper + lower) / 2
    slash_height = (lower - upper) or 12.0
    hosts = _find_overlay_hosts(manifest, overlay, page=page, x=x, y=y)
    if len(hosts) > 1:
        return "ambiguous-host", None
    if not hosts:
        return "no-host", None
    host, host_box, top, bottom = hosts[0]
    height = max(bottom - top, 1e-6)
    width = max(host_box.right - host_box.left, 1e-6)
    # The host tolerance lets a slash sit just outside the box:
    # clamp once, so the text and the grid paths see the same span.
    y_fraction = min(max((y - top) / height, 0.0), 1.0)
    x_fraction = min(max((x - host_box.left) / width, 0.0), 1.0)
    outcome = _compose_in_host(host, x_fraction, y_fraction, height, slash_height)
    if outcome == "composed":
        host.metadata["negation_overlays"] = (
            host.metadata.get("negation_overlays", 0) + 1
        )
    return outcome, host.id


def _reattach_negation_overlays(manifest: ProcessingManifest) -> dict[str, int]:
    """Give each detached ``≠`` slash back to the relation it negates.

    A legacy TeX text layer may extract the slash TeX lays over ``=`` as its own
    element (``U+0338`` alone), leaving ``h = 0`` where the page says
    ``h ≠ 0``. The slash's box is the only link back: the element containing it
    is found on the same page, the slash's position inside it is estimated, and
    ``docstruct.text.negation_overlay`` picks the relation only when the choice
    is unambiguous — composing the wrong ``=`` would invert a true statement.
    A formula whose text is already LaTeX (recognized, #253) is not touched.

    Every slash element is then left out of the payload (``negation_overlay``
    metadata, with the outcome: ``composed``, ``host-is-latex``, ``ambiguous``,
    ``no-candidate``, ``ambiguous-host`` or ``no-host``), since a lone
    combining mark says nothing to a reader. A slash already recorded is
    skipped, so running the handler again (a plan retry) keeps the first
    outcome instead of re-reading a host whose text it already changed.
    Returns the count per outcome.

    This runs only with the repair obligation (``LEGACY_UNICODE_REPAIR=repair``).
    ``detect`` keeps its meaning — report, deliver as extracted — so there the
    slash elements stay in the outputs, like every other legacy artifact.
    """
    outcomes: dict[str, int] = {}
    overlays = [
        element
        for element in manifest.elements
        if is_detached_overlay(element.text)
        and "negation_overlay" not in element.metadata
    ]
    for overlay in overlays:
        outcome, host_id = _resolve_single_overlay(manifest, overlay)
        overlay.metadata["negation_overlay"] = {"outcome": outcome, "host": host_id}
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    if outcomes:
        logger.info("Detached negation slashes: {}", outcomes)
    return outcomes


def _collect_unicode_repair_targets(
    elements: list[ManifestElement],
) -> tuple[list[tuple[ManifestElement, str]], dict[str, Detection]]:
    eligible: list[tuple[ManifestElement, str]] = []
    detections: dict[str, Detection] = {}
    for element in elements:
        text = unicode_repair_text(element)
        if not text or is_detached_overlay(element.text):
            continue
        block_type = (
            "table"
            if element.type == "table"
            else _UNICODE_REPAIR_BLOCK_TYPES.get(element.type)
        )
        if block_type is None:
            continue
        eligible.append((element, block_type))
        detections[element.id] = detect_legacy_unicode(text)
    return eligible, detections


def _document_word_internal_count(
    manifest: ProcessingManifest, detections: dict[str, Detection]
) -> int:
    # The threshold is document-level. The builder emits one obligation for all
    # eligible elements, and records the count in its observation; read it from
    # there so a future split of the obligation cannot change the decision.
    observation = next(
        (
            item
            for item in getattr(manifest, "observations", [])
            if item.kind == "repair-legacy-unicode-detected"
        ),
        None,
    )
    if observation is not None and "spacing_word_internal" in observation.evidence:
        return int(observation.evidence["spacing_word_internal"])
    return sum(
        detection.spacing_word_internal for detection in detections.values()
    )


def _apply_unicode_repair_to_element(
    element: ManifestElement,
    block_type: str,
    *,
    language: str,
    detection: Detection,
    allow_standalone: bool,
) -> tuple[bool, bool]:
    # A word-internal spacing accent (``C´ alculo``) is legacy extraction
    # evidence. Standalone accents (separated from their word) are only
    # included when the document has enough of the word-internal shape;
    # the lib never touches protected spans. The crase and split-ligature
    # rules rest on that same document-level evidence alone: an element
    # may carry ``` a`` or ``fi ca`` without any spaced accent of its own.
    allow_spacing = detection.spacing_diacritics > 0
    context = UnicodeRepairContext(
        language=language,
        block_type="prose" if block_type == "table" else block_type,
        page=element.page_number,
        allow_spacing_diacritics=allow_spacing,
        allow_standalone_spacing_diacritics=allow_spacing and allow_standalone,
        allow_legacy_tex_artifacts=allow_standalone,
    )
    if block_type == "table":
        edited, rules, edits, needs_review = _repair_table_cells(element, context)
        element.metadata["unicode_repair"] = {
            "edited": edited,
            "rules": sorted(rules),
            "edits": edits,
            "needs_review": needs_review,
            "confidence": None,
        }
        return edited, needs_review

    original = element.text or ""
    decision = repair_legacy_unicode(original, context=context)
    edited = decision.repaired != original
    if edited:
        element.text = decision.repaired
    element.metadata["unicode_repair"] = {
        "edited": edited,
        "rules": sorted({edit.rule for edit in decision.edits}),
        "edits": len(decision.edits),
        "needs_review": decision.needs_review,
        "confidence": decision.confidence,
    }
    return edited, decision.needs_review


def _handle_unicode_repair_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Repair legacy Unicode: NFD, dotless i, spacing diacritics, the crase and split ligatures.

    Only selected, prose-like elements are touched. Word-internal spacing
    accents are repaired whenever the element shows them; standalone accents
    are only repaired when the document has enough word-internal evidence
    (recorded in the manifest observation). The decision metadata records the
    edits and keeps ``needs_review`` for signals that remain, without copying
    the whole text into the manifest.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    # Before the per-element repair, so the reattached ``≠`` is in the text
    # the repair reads, and the slash elements are not counted for review.
    _reattach_negation_overlays(manifest)

    eligible, detections = _collect_unicode_repair_targets(elements)
    if not eligible:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_UNICODE_REPAIR_NO_TEXT),
        )

    language = manifest.language or "pt-BR"
    allow_standalone = (
        _document_word_internal_count(manifest, detections)
        >= _UNICODE_STANDALONE_SPACING_MIN
    )
    inspected = len(eligible)
    repaired = 0
    review = 0
    for element, block_type in eligible:
        edited, needs_review = _apply_unicode_repair_to_element(
            element,
            block_type,
            language=language,
            detection=detections[element.id],
            allow_standalone=allow_standalone,
        )
        if edited:
            repaired += 1
        if needs_review:
            review += 1
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_UNICODE_REPAIR_APPLIED, inspected).format(
            done=repaired, total=inspected, review=review
        ),
    )
