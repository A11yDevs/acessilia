"""The inline math stage: mark the math runs inside text and table cells.

Runs before planning, when inline math detection is enabled. It reads the
source's text spans through the core's per-document reader (``_TextSpanReader``,
which binds ``backend.tools.text_spans`` and records a failure in
``configuration["inline_math_detection"]``), finds the math runs of each boxed
element with ``docstruct.text.inline_math``, splices them into the text or the
table cells, and claims the negation slashes that overlay a relation. Moved
verbatim from the PDDL orchestrator (#402, phase 3, step 6).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from docstruct.geometry.boxes import holds_point
from docstruct.tables.ast import (
    TABLE_SECTIONS,
)
from docstruct.text.inline_math import (
    Placement,
    assign_runs_to_cells,
    detect_inline_math_by_page,
    splice_inline_math,
    top_left_box,
)
from docstruct.text.negation_overlay import (
    is_detached_overlay,
)

from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from backend.core.pipeline.elements import (
    _OVERLAY_HOST_TOLERANCE,
    _bbox,
)
from backend.core.pipeline.toolbox import (
    _source_artifact_id,
)
from backend.tools.logger import logger

#: Element types whose text the exporters render as prose with inline math.
_INLINE_MATH_ELEMENT_TYPES = frozenset({"paragraph", "list_item", "caption", "footnote"})


class _TextSpanReader:
    """The text layer's spans of one document, each page fetched once (#260).

    The prose and table steps of the inline math detection run at different
    points of the pipeline; reading through one reader, a page is requested
    from the Toolbox once, and a capability that failed is not asked again.
    """

    def __init__(self, manifest: ProcessingManifest, source_path: Path) -> None:
        self._manifest = manifest
        self._source_path = source_path
        self._pages: dict[int, dict[str, Any]] = {}
        self._failed = False

    async def pages(self, wanted: Iterable[int]) -> dict[int, dict[str, Any]] | None:
        """The spans of every page read so far, ``wanted`` included; ``None`` when
        the Toolbox cannot read them (recorded as ``unavailable``)."""
        from acessilia_sdk.toolbox.errors import ToolboxError

        from backend.tools.text_spans import fetch_text_spans

        if self._failed:
            return None
        missing = sorted(set(wanted) - set(self._pages))
        if missing:
            try:
                self._pages.update(
                    await fetch_text_spans(
                        self._source_path, missing, artifact_id=_source_artifact_id(self._manifest)
                    )
                )
            except ToolboxError as exc:
                logger.info("Inline math detection skipped: document.text.spans failed ({})", exc)
                self._manifest.extractor.configuration["inline_math_detection"] = "unavailable"
                self._failed = True
                return None
        return self._pages


def _inline_math_enabled(manifest: ProcessingManifest) -> bool:
    from backend.config.settings import settings

    return (
        settings.inline_math_detection == "fonts"
        and manifest.source.media_type == "application/pdf"
    )


def _boxed_pages(elements: Iterable[ManifestElement]) -> list[int]:
    return sorted(
        {
            provenance.page_number
            for element in elements
            for provenance in element.provenance
            if provenance.bbox is not None
        }
    )


async def _mark_inline_math(
    manifest: ProcessingManifest,
    source_path: Path,
    text_spans: _TextSpanReader | None = None,
) -> dict[str, int]:
    """Write the inline math of PDF prose as ``$…$``, from the text layer's fonts (#265).

    Docling reports no inline formula region for a typeset PDF, so
    ``s(t) = t³`` arrives as ``s ( t ) = t 3``. The text layer still has the
    fonts and baselines (ADR 0011): the Toolbox's ``document.text.spans``
    returns them, ``docstruct.text.inline_math`` finds each run of math in an
    element's lines and rebuilds its LaTeX, and splices it into the element's
    text where both character sequences align. The canonical enrichment then
    converts each span (MathML, speech).

    A negation slash the run composed into its relation (``h \neq 0``) is
    recorded on its detached-slash element (``negation_overlay`` outcome
    ``inline-math``), so the later reattachment does not compose another
    ``=`` of the paragraph. Returns ``{elements, marked, unmatched}``; the
    detection is skipped for other media, with ``INLINE_MATH_DETECTION=off``
    and when the Toolbox cannot read the spans.
    """
    counts = {"elements": 0, "marked": 0, "unmatched": 0}
    if not _inline_math_enabled(manifest):
        return counts
    candidates = [
        element
        for element in manifest.elements
        if element.type in _INLINE_MATH_ELEMENT_TYPES
        and (element.text or "").strip()
        and "inline_math_detection" not in element.metadata
        and any(provenance.bbox is not None for provenance in element.provenance)
    ]
    pages = _boxed_pages(candidates)
    if not pages:
        return counts
    spans = await (text_spans or _TextSpanReader(manifest, source_path)).pages(pages)
    if spans is None:
        return counts

    heights = {page.page_number: page.height for page in manifest.pages}
    overlays = [element for element in manifest.elements if is_detached_overlay(element.text)]
    for element in candidates:
        detection = detect_inline_math_by_page(_placements(element), spans, heights)
        if not detection.runs:
            continue
        result = splice_inline_math(element.text or "", detection)
        counts["elements"] += 1
        counts["marked"] += len(result.marked)
        counts["unmatched"] += len(result.unmatched)
        element.metadata["inline_math_detection"] = {
            "marked": len(result.marked),
            "unmatched": len(result.unmatched),
        }
        if not result.marked:
            continue
        element.text = result.text
        for run in result.marked:
            for slash in run.negations:
                _claim_negation_overlay(overlays, element, slash, run.page, spans, heights)
    manifest.extractor.configuration["inline_math_detection"] = "fonts"
    if counts["elements"]:
        logger.info("Inline math from the text layer's fonts: {}", counts)
    return counts


async def _mark_table_inline_math(
    manifest: ProcessingManifest,
    source_path: Path,
    text_spans: _TextSpanReader | None = None,
) -> dict[str, int]:
    """Write the inline math of PDF table cells as ``$…$`` (#260).

    The prose step's detection over the table's text-layer lines, run after
    the table enrichment so a table read again keeps its marks. A table's
    cells carry no boxes: ``assign_runs_to_cells`` gives each run to the cell
    whose text holds it, and each cell is spliced on its own. A fraction set
    in a header cell (two stacked script-size lines) becomes ``\\frac``.
    Returns ``{elements, marked, unmatched}``, skipping as the prose step does.
    """
    counts = {"elements": 0, "marked": 0, "unmatched": 0}
    if not _inline_math_enabled(manifest):
        return counts
    tables = [
        element
        for element in manifest.elements
        if element.type == "table"
        and isinstance(element.metadata.get("table_ast"), dict)
        and "inline_math_detection" not in element.metadata
        and any(provenance.bbox is not None for provenance in element.provenance)
    ]
    pages = _boxed_pages(tables)
    if not pages:
        return counts
    spans = await (text_spans or _TextSpanReader(manifest, source_path)).pages(pages)
    if spans is None:
        return counts

    heights = {page.page_number: page.height for page in manifest.pages}
    overlays = [element for element in manifest.elements if is_detached_overlay(element.text)]
    for table in tables:
        detection = detect_inline_math_by_page(_placements(table), spans, heights)
        if not detection.runs:
            continue
        cells = [
            cell
            for section in TABLE_SECTIONS
            for row in table.metadata["table_ast"].get(section) or []
            if isinstance(row, dict)
            for cell in row.get("cells") or []
            if isinstance(cell, dict) and isinstance(cell.get("text"), str)
        ]
        detections, left_out = assign_runs_to_cells(detection, [cell["text"] for cell in cells])
        marked, unmatched = [], list(left_out)
        for cell, cell_detection in zip(cells, detections):
            if not cell_detection.runs:
                continue
            result = splice_inline_math(cell["text"], cell_detection)
            cell["text"] = result.text
            marked.extend(result.marked)
            unmatched.extend(result.unmatched)
        counts["elements"] += 1
        counts["marked"] += len(marked)
        counts["unmatched"] += len(unmatched)
        table.metadata["inline_math_detection"] = {
            "marked": len(marked),
            "unmatched": len(unmatched),
        }
        for run in marked:
            for slash in run.negations:
                _claim_negation_overlay(overlays, table, slash, run.page, spans, heights)
    if counts["elements"]:
        logger.info("Inline math of table cells from the text layer's fonts: {}", counts)
    return counts


def _placements(element: ManifestElement) -> list[Placement]:
    """The element's pages and boxes, as ``docstruct.text.inline_math`` reads them."""
    return [(provenance.page_number, provenance.bbox) for provenance in element.provenance]


def _claim_negation_overlay(
    overlays: list[ManifestElement],
    host: ManifestElement,
    slash: tuple[float, float, float, float],
    page: int,
    spans: dict[int, dict[str, Any]],
    heights: dict[int, float | None],
) -> None:
    """Record the detached slash at ``slash`` as composed by the inline math of ``host``."""
    x, y = (slash[0] + slash[2]) / 2, (slash[1] + slash[3]) / 2
    for overlay in overlays:
        if "negation_overlay" in overlay.metadata:
            continue
        located = _bbox(overlay, page)
        if located is None:
            continue
        box = top_left_box(located[1], page, spans, heights)
        if box is None:
            continue
        if holds_point(box, x, y, _OVERLAY_HOST_TOLERANCE * 2):
            overlay.metadata["negation_overlay"] = {"outcome": "inline-math", "host": host.id}
            return
