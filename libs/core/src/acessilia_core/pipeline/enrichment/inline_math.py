"""The inline math stage: mark the math runs inside text and table cells.

Runs inside the plan since core 0.3.20, as the ``inline-math-marker`` method
of the document's ``mark-inline-math`` obligation (#640, M4b): it marks the
prose, and the tables whose marks went stale; a block the plan adds gets its
marks on the replan, which replaced the pass after execution of #599. The
table enrichment marks its tables' cells. It reads the source's text
spans through the core's per-document reader (``_TextSpanReader``, which binds
``acessilia_core.toolbox.text_spans``; a step that gets ``None`` records the
failure in ``configuration["inline_math_detection"]``), finds the math runs of
each boxed element with ``docstruct.text.inline_math``, splices them into the
text or the table cells, and claims the negation slashes that overlay a
relation. Moved verbatim from the PDDL orchestrator (#402, phase 3, step 6).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from acessilia_core.config import DocumentConfig, ToolboxConfig
from acessilia_core.logger import logger
from acessilia_core.manifest.models import ManifestElement, ProcessingManifest
from acessilia_core.pipeline.elements import _OVERLAY_HOST_TOLERANCE, _bbox
from acessilia_core.pipeline.toolbox import _source_artifact_id
from acessilia_core.ports import RunPorts
from docstruct.geometry.boxes import holds_point
from docstruct.tables.ast import TABLE_SECTIONS
from docstruct.text.inline_math import (
    Placement,
    assign_runs_to_cells,
    detect_inline_math_by_page,
    splice_inline_math,
    top_left_box,
)
from docstruct.text.negation_overlay import is_detached_overlay

#: Element types whose text the exporters render as prose with inline math.
_INLINE_MATH_ELEMENT_TYPES = frozenset({"paragraph", "list_item", "caption", "footnote"})


class _TextSpanReader:
    """The text layer's spans of one document, each page fetched once (#260).

    The prose and table steps of the inline math detection run as different
    planned methods (``inline-math-marker`` and ``table-enrichment``, #640
    M4b and M2); reading through one reader, a page is requested from the
    Toolbox once, and a capability that failed is not asked again.

    The reader keeps only what identifies the source (its path and artifact
    id), not the manifest: the plan's executor works on a copy of it. A step
    that gets ``None`` records the detection as ``unavailable`` on the
    manifest it is enriching.
    """

    def __init__(
        self, manifest: ProcessingManifest, source_path: Path, toolbox: ToolboxConfig
    ) -> None:
        self._artifact_id = _source_artifact_id(manifest)
        self._source_path = source_path
        self._toolbox = toolbox
        self._pages: dict[int, dict[str, Any]] = {}
        self._failed = False

    async def pages(self, wanted: Iterable[int]) -> dict[int, dict[str, Any]] | None:
        """The spans of every page read so far, ``wanted`` included; ``None`` when
        the Toolbox cannot read them (recorded as ``unavailable``)."""
        from acessilia_core.toolbox.text_spans import fetch_text_spans
        from acessilia_sdk.toolbox.errors import ToolboxError

        if self._failed:
            return None
        missing = sorted(set(wanted) - set(self._pages))
        if missing:
            try:
                self._pages.update(
                    await fetch_text_spans(
                        self._source_path,
                        missing,
                        toolbox=self._toolbox,
                        artifact_id=self._artifact_id,
                    )
                )
            except ToolboxError as exc:
                logger.info("Inline math detection skipped: document.text.spans failed ({})", exc)
                self._failed = True
                return None
        return self._pages


def run_text_spans(
    ports: RunPorts, manifest: ProcessingManifest, source_path: Path, toolbox: ToolboxConfig
) -> _TextSpanReader:
    """The text-span reader of the run (``ports``), so a page is fetched once
    for the prose step and the table step, both inside the plan.

    One per run: the first call builds it, from its ``manifest``,
    ``source_path`` and ``toolbox``, and every later call gets that reader
    whatever it passes (``RunServices.shared``). A run is one document.
    """
    return ports.services.shared(
        "text-spans", lambda: _TextSpanReader(manifest, source_path, toolbox)
    )


def _inline_math_enabled(manifest: ProcessingManifest, document: DocumentConfig) -> bool:
    return (
        document.inline_math_detection == "fonts"
        and manifest.source.media_type == "application/pdf"
    )


def inline_math_detection_status(manifest: ProcessingManifest, document: DocumentConfig) -> str:
    """How the detection ran, for the steps' messages: ``off`` (disabled, or
    not a PDF), ``unavailable`` (the Toolbox could not read the text layer)
    or ``fonts`` (the marks ran)."""
    if not _inline_math_enabled(manifest, document):
        return "off"
    if manifest.extractor.configuration.get("inline_math_detection") == "unavailable":
        return "unavailable"
    return "fonts"


def _boxed_pages(elements: Iterable[ManifestElement]) -> list[int]:
    return sorted(
        {
            provenance.page_number
            for element in elements
            for provenance in element.provenance
            if provenance.bbox is not None
        }
    )


def _is_prose_inline_math_candidate(element: ManifestElement) -> bool:
    return (
        element.type in _INLINE_MATH_ELEMENT_TYPES
        and bool((element.text or "").strip())
        and "inline_math_detection" not in element.metadata
        and any(provenance.bbox is not None for provenance in element.provenance)
    )


def _is_table_inline_math_candidate(element: ManifestElement) -> bool:
    return (
        element.type == "table"
        and isinstance(element.metadata.get("table_ast"), dict)
        and "inline_math_detection" not in element.metadata
        and any(provenance.bbox is not None for provenance in element.provenance)
    )


def _claim_run_negations(
    overlays: list[ManifestElement],
    host: ManifestElement,
    marked: Iterable[Any],
    spans: dict[int, dict[str, Any]],
    heights: dict[int, float | None],
) -> None:
    for run in marked:
        for slash in run.negations:
            _claim_negation_overlay(overlays, host, slash, run.page, spans, heights)


def _splice_prose_element(
    element: ManifestElement,
    *,
    spans: dict[int, dict[str, Any]],
    heights: dict[int, float | None],
    overlays: list[ManifestElement],
    counts: dict[str, int],
) -> None:
    detection = detect_inline_math_by_page(_placements(element), spans, heights)
    if not detection.runs:
        return
    result = splice_inline_math(element.text or "", detection)
    counts["elements"] += 1
    counts["marked"] += len(result.marked)
    counts["unmatched"] += len(result.unmatched)
    element.metadata["inline_math_detection"] = {
        "marked": len(result.marked),
        "unmatched": len(result.unmatched),
    }
    if not result.marked:
        return
    element.text = result.text
    _claim_run_negations(overlays, element, result.marked, spans, heights)


def _table_text_cells(table: ManifestElement) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for section in TABLE_SECTIONS:
        for row in table.metadata["table_ast"].get(section) or []:
            if not isinstance(row, dict):
                continue
            for cell in row.get("cells") or []:
                if isinstance(cell, dict) and isinstance(cell.get("text"), str):
                    cells.append(cell)
    return cells


def _splice_table_element(
    table: ManifestElement,
    *,
    spans: dict[int, dict[str, Any]],
    heights: dict[int, float | None],
    overlays: list[ManifestElement],
    counts: dict[str, int],
) -> None:
    detection = detect_inline_math_by_page(_placements(table), spans, heights)
    if not detection.runs:
        return
    cells = _table_text_cells(table)
    detections, left_out = assign_runs_to_cells(
        detection, [cell["text"] for cell in cells]
    )
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
    _claim_run_negations(overlays, table, marked, spans, heights)


async def _mark_inline_math(
    manifest: ProcessingManifest,
    source_path: Path,
    document: DocumentConfig,
    text_spans: _TextSpanReader,
    *,
    targets: frozenset[str] | None = None,
) -> dict[str, int]:
    """Write the inline math of PDF prose as ``$…$``, from the text layer's fonts (#265).

    Docling reports no inline formula region for a typeset PDF, so
    ``s(t) = t³`` arrives as ``s ( t ) = t 3``. The text layer still has the
    fonts and baselines (ADR 0011): the Toolbox's ``document.text.spans``
    returns them, ``docstruct.text.inline_math`` finds each run of math in an
    element's lines and rebuilds its LaTeX, and splices it into the element's
    text where both character sequences align. The canonical enrichment then
    converts each span (MathML, speech).

    A negation slash the run composed into its relation (``h \\neq 0``) is
    recorded on its detached-slash element (``negation_overlay`` outcome
    ``inline-math``), so the later reattachment does not compose another
    ``=`` of the paragraph. Returns ``{elements, marked, unmatched}``; the
    detection is skipped for other media, with ``INLINE_MATH_DETECTION=off``
    and when the Toolbox cannot read the spans.
    """
    counts = {"elements": 0, "marked": 0, "unmatched": 0}
    if not _inline_math_enabled(manifest, document):
        return counts
    candidates = [
        element
        for element in manifest.elements
        if _is_prose_inline_math_candidate(element)
        and (targets is None or element.id in targets)
    ]
    pages = _boxed_pages(candidates)
    if not pages:
        return counts
    spans = await text_spans.pages(pages)
    if spans is None:
        # The reader keeps no manifest: the step records it on the one it
        # enriches, the copy the plan's executor returns included.
        manifest.extractor.configuration["inline_math_detection"] = "unavailable"
        return counts

    heights = {page.page_number: page.height for page in manifest.pages}
    overlays = [
        element for element in manifest.elements if is_detached_overlay(element.text)
    ]
    for element in candidates:
        _splice_prose_element(
            element, spans=spans, heights=heights, overlays=overlays, counts=counts
        )
    manifest.extractor.configuration["inline_math_detection"] = "fonts"
    if counts["elements"]:
        logger.info("Inline math from the text layer's fonts: {}", counts)
    return counts


async def _mark_table_inline_math(
    manifest: ProcessingManifest,
    source_path: Path,
    document: DocumentConfig,
    text_spans: _TextSpanReader,
    *,
    targets: frozenset[str] | None = None,
) -> dict[str, int]:
    """Write the inline math of PDF table cells as ``$…$`` (#260).

    The prose step's detection over the table's text-layer lines, run after
    the table enrichment so a table read again keeps its marks. A table's
    cells carry no boxes: ``assign_runs_to_cells`` gives each run to the cell
    whose text holds it, and each cell is spliced on its own. A fraction set
    in a header cell (two stacked script-size lines) becomes ``\\frac``.
    Returns ``{elements, marked, unmatched}``, skipping as the prose step does.
    ``targets`` limits the marks to those tables (an obligation's, #832);
    ``None`` is every table. The overlays stay the whole document's context.
    """
    counts = {"elements": 0, "marked": 0, "unmatched": 0}
    if not _inline_math_enabled(manifest, document):
        return counts
    tables = [
        element
        for element in manifest.elements
        if _is_table_inline_math_candidate(element)
        and (targets is None or element.id in targets)
    ]
    pages = _boxed_pages(tables)
    if not pages:
        return counts
    spans = await text_spans.pages(pages)
    if spans is None:
        # The reader keeps no manifest: the step records it on the one it
        # enriches, the copy the plan's executor returns included.
        manifest.extractor.configuration["inline_math_detection"] = "unavailable"
        return counts

    heights = {page.page_number: page.height for page in manifest.pages}
    overlays = [
        element for element in manifest.elements if is_detached_overlay(element.text)
    ]
    for table in tables:
        _splice_table_element(
            table, spans=spans, heights=heights, overlays=overlays, counts=counts
        )
    if counts["elements"]:
        logger.info("Inline math of table cells from the text layer's fonts: {}", counts)
    return counts


def _carries_inline_math(element: ManifestElement) -> bool:
    """Whether a block already carries a ``$…$`` span (a table's cells included)."""
    if "$" in (element.text or ""):
        return True
    return element.type == "table" and "$" in str(
        element.metadata.get("table_ast") or ""
    )


def _invalidate_formula_conversions(manifest: ProcessingManifest) -> None:
    """Drop the planned formula conversions a new block can contradict.

    The ``mathml`` and ``latex-verbalizer`` handlers mark implicit products
    with the variables the manifest had when they ran. A block added during the
    plan can carry variable evidence they never saw, either already written as
    ``$…$`` or marked by the inline math step on the replan (#640, M4b). The canonical build reuses
    ``metadata["mathml"]`` and ``metadata["verbalization"]`` when present, so
    keeping them would ship a conversion made with the old variables; dropping
    them makes the build redo every formula with the final manifest. The LaTeX
    and ``latex_normalized`` stay.
    """
    for element in manifest.elements:
        if element.type == "formula" and (element.text or "").strip():
            element.metadata.pop("mathml", None)
            element.metadata.pop("verbalization", None)


def inline_math_pending(manifest: ProcessingManifest) -> list[str]:
    """The elements the inline math step still has work on, in document order.

    In a PDF:
    - the prose elements with boxes and text that no detection has marked
      yet, which the detection marks;
    - the prose elements without boxes that already carry a ``$…$`` span: the
      detection cannot read them, but they are variable evidence the formula
      conversions may not have seen, which the step's invalidation weighs;
    - the tables whose marks went stale (``inline_math_renewed``).

    A block the plan added (a ``rescue-omitted`` paragraph) is one of them,
    so it gets the step on the replan (#640, M4b) instead of in a pass after
    execution (#599). Whether the detection is on is the run's config, not
    the manifest's: with it off the step marks nothing, but still weighs the
    evidence a block already carries, as the pass after execution did.
    """
    if manifest.source.media_type != "application/pdf":
        return []
    renewed = inline_math_renewed(manifest)
    return [
        element.id for element in manifest.elements
        if _is_prose_inline_math_candidate(element)
        or _carries_unread_inline_math(element)
        or element.id in renewed
    ]


def inline_math_renewed(manifest: ProcessingManifest) -> set[str]:
    """The tables whose inline math marks went stale (``inline_math_stale``):
    the select-table-source step adopted the secondary provider's cells after
    they were marked.

    The step clears the flag when it marks a table, so a flagged table that a
    satisfied obligation of the step covers was adopted again after it: its
    earlier marks no longer hold, and it joins a new obligation
    (``DocumentStep.renewed``)."""
    if manifest.source.media_type != "application/pdf":
        return set()
    return {
        element.id for element in manifest.elements
        if element.metadata.get("inline_math_stale") and _is_table_inline_math_candidate(element)
    }


def _carries_unread_inline_math(element: ManifestElement) -> bool:
    """A prose element the detection cannot read (no boxes) that already
    carries ``$…$``, and that no detection has marked."""
    return (
        element.type in _INLINE_MATH_ELEMENT_TYPES
        and "inline_math_detection" not in element.metadata
        and not any(provenance.bbox is not None for provenance in element.provenance)
        and _carries_inline_math(element)
    )


async def _enrich_inline_math(
    manifest: ProcessingManifest,
    source_path: Path,
    document: DocumentConfig,
    text_spans: _TextSpanReader,
    *,
    targets: frozenset[str] | None = None,
) -> dict[str, int]:
    """Mark the inline math of ``targets`` (``None``: every candidate): the
    prose, then the stale tables, whose flag is cleared once tried. Returns
    the sum of both steps' ``{elements, marked, unmatched}``.

    The run's text-span reader (``RunPorts.services``) is the one the table
    enrichment uses, so a page already fetched is not requested again and a
    capability that failed is not asked again.
    """
    prose = await _mark_inline_math(manifest, source_path, document, text_spans, targets=targets)
    stale = frozenset(
        element.id for element in manifest.elements
        if element.metadata.get("inline_math_stale") and (targets is None or element.id in targets)
    )
    tables = (
        await _mark_table_inline_math(manifest, source_path, document, text_spans, targets=stale)
        if stale else {"elements": 0, "marked": 0, "unmatched": 0}
    )
    for element in manifest.elements:
        if element.id in stale:
            element.metadata.pop("inline_math_stale", None)
    return {key: prose[key] + tables[key] for key in prose}


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
