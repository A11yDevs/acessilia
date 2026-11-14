"""Deterministic handlers that repair text in place.

Unicode and negation-overlay repair, normalization, the repetition guard, line
numbers, verse chunking, tail joins and the heading hierarchy. None calls a
model or the Toolbox. Moved verbatim from the PDDL orchestrator (#402, phase 3,
step 6); ``handlers/registry.py``'s ``METHOD_HANDLERS`` registers them.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from docstruct.fusion.noise import (
    element_role,
)
from docstruct.fusion.tailjoin import page_number_position
from docstruct.geometry.boxes import downward_edges
from docstruct.tables.ast import (
    TABLE_SECTIONS,
)
from docstruct.text.latex import has_latex_markup
from docstruct.text.norm_fix import norm_fix
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

from backend.core.execution.models import MethodResult
from backend.core.manifest.builder import (
    unicode_repair_text,
)
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from backend.tools.logger import logger
from backend.core.pipeline.elements import (
    _OVERLAY_HOST_TOLERANCE,
    _bbox,
    _element_bbox,
)
from backend.core.pipeline.handlers.common import (
    _fusion_agent,
    _missing_obligation,
    _target_elements,
)
from backend.core.pipeline.handlers.messages import (
    MSG_BLOCK_COUNT,
    MSG_HEADING_NONE,
    MSG_HEADING_REPAIRED,
    MSG_LINE_NUMBERS_EXTRACTED,
    MSG_LINE_NUMBERS_NONE,
    MSG_NORMALIZE_APPLIED,
    MSG_NORMALIZE_NO_TEXT,
    MSG_REPETITION_NONE,
    MSG_REPETITION_REMOVED,
    MSG_TAILJOIN_JOINED,
    MSG_TAILJOIN_MISMATCH,
    MSG_TAILJOIN_NONE,
    MSG_UNICODE_REPAIR_APPLIED,
    MSG_UNICODE_REPAIR_NO_TEXT,
    MSG_VERSE_NONE,
    MSG_VERSE_SPLIT,
)
from backend.core.pipeline.handlers.structure import (
    joined_provenance,
    remap_references,
    replace_elements,
    split_provenance,
    unique_element_id,
)
from backend.core.i18n import n, t


def _handle_norm_fix_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Apply the deterministic text cleanups (ligatures, hyphenation, NBSP)."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fixed = 0
    for element in elements:
        current = element.text or ""
        if not current:
            continue
        cleaned = norm_fix(current)
        if cleaned != current:
            element.text = cleaned
            element.metadata["norm_fixed"] = True
        fixed += 1

    if not fixed:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_NORMALIZE_NO_TEXT),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_NORMALIZE_APPLIED, fixed).format(count=fixed),
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
        if is_detached_overlay(element.text) and "negation_overlay" not in element.metadata
    ]
    for overlay in overlays:
        located = _bbox(overlay)
        outcome, host_id = "no-host", None
        if located is not None:
            page, box = located
            x = (box.left + box.right) / 2
            upper, lower = downward_edges(box)
            y = (upper + lower) / 2
            slash_height = (lower - upper) or 12.0
            hosts = []
            for element in manifest.elements:
                if element is overlay or is_detached_overlay(element.text):
                    continue
                other = _bbox(element, page)
                if other is None:
                    continue
                top, bottom = downward_edges(other[1])
                if (
                    other[1].left - _OVERLAY_HOST_TOLERANCE <= x <= other[1].right + _OVERLAY_HOST_TOLERANCE
                    and top - _OVERLAY_HOST_TOLERANCE <= y <= bottom + _OVERLAY_HOST_TOLERANCE
                ):
                    hosts.append((element, other[1], top, bottom))
            if len(hosts) > 1:
                outcome = "ambiguous-host"
            elif hosts:
                host, host_box, top, bottom = hosts[0]
                host_id = host.id
                height = max(bottom - top, 1e-6)
                width = max(host_box.right - host_box.left, 1e-6)
                # The host tolerance lets a slash sit just outside the box:
                # clamp once, so the text and the grid paths see the same span.
                y_fraction = min(max((y - top) / height, 0.0), 1.0)
                x_fraction = min(max((x - host_box.left) / width, 0.0), 1.0)
                outcome = _compose_in_host(host, x_fraction, y_fraction, height, slash_height)
                if outcome == "composed":
                    host.metadata["negation_overlays"] = host.metadata.get("negation_overlays", 0) + 1
        overlay.metadata["negation_overlay"] = {"outcome": outcome, "host": host_id}
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    if outcomes:
        logger.info("Detached negation slashes: {}", outcomes)
    return outcomes


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
    outcome, text = compose_in_text(host.text or "", x_fraction, y_fraction, height, slash_height)
    if text is not None:
        host.text = text
    return outcome


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

    language = manifest.language or "pt-BR"
    eligible: list[tuple[ManifestElement, str]] = []
    detections: dict[str, Detection] = {}
    for element in elements:
        text = unicode_repair_text(element)
        if not text or is_detached_overlay(element.text):
            continue
        if element.type == "table":
            block_type = "table"
        else:
            block_type = _UNICODE_REPAIR_BLOCK_TYPES.get(element.type)
            if block_type is None:
                continue
        eligible.append((element, block_type))
        detections[element.id] = detect_legacy_unicode(text)

    if not eligible:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_UNICODE_REPAIR_NO_TEXT),
        )

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
        word_internal = int(observation.evidence["spacing_word_internal"])
    else:
        word_internal = sum(
            detection.spacing_word_internal for detection in detections.values()
        )
    allow_standalone = word_internal >= _UNICODE_STANDALONE_SPACING_MIN
    inspected = len(eligible)
    repaired = 0
    review = 0
    for element, block_type in eligible:
        detection = detections[element.id]
        original = element.text or ""
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
            edited, rules, edits, needs_review = _repair_table_cells(
                element, context
            )
            if edited:
                repaired += 1
            if needs_review:
                review += 1
            element.metadata["unicode_repair"] = {
                "edited": edited,
                "rules": sorted(rules),
                "edits": edits,
                "needs_review": needs_review,
                "confidence": None,
            }
            continue
        decision = repair_legacy_unicode(original, context=context)
        if decision.repaired != original:
            element.text = decision.repaired
            repaired += 1
        element.metadata["unicode_repair"] = {
            "edited": decision.repaired != original,
            "rules": sorted({edit.rule for edit in decision.edits}),
            "edits": len(decision.edits),
            "needs_review": decision.needs_review,
            "confidence": decision.confidence,
        }
        if decision.needs_review:
            review += 1
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_UNICODE_REPAIR_APPLIED, inspected).format(
            done=repaired, total=inspected, review=review
        ),
    )


def _handle_repetition_guard_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Remove repeated token loops from the obligation's current page text."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fusion_agent = _fusion_agent()
    cut_total = 0
    for element in elements:
        result = fusion_agent.process_guard_repetition(element.text or "")
        cut = int(result["tokens_cut"])
        if not cut:
            continue
        element.text = result["text"]
        element.metadata["repetition_guard"] = {"tokens_cut": cut}
        cut_total += cut

    if not cut_total:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_REPETITION_NONE),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_REPETITION_REMOVED, cut_total).format(
            count=cut_total
        ),
    )


def _element_blocks(
    elements: list[ManifestElement],
    manifest: ProcessingManifest,
) -> list[dict[str, Any]]:
    """Manifest elements as the fusion stack's block dicts.

    The deterministic primitives in `docstruct` operate on classified blocks, not
    on bare strings, so the elements are adapted once here instead of each handler
    guessing at a signature. The builder sends every target of these handlers as
    ``kind="text"`` (it derives them from text elements), so the adapter does the
    same instead of narrowing headings and list items out of the algorithm.
    """
    blocks: list[dict[str, Any]] = []
    for element in elements:
        bbox = _element_bbox(element, manifest)
        blocks.append(
            {
                "md": element.text or "",
                "text": element.text or "",
                "kind": "text",
                "type": element.type,
                "role": element_role(element),
                "box": list(bbox) if bbox else None,
            }
        )
    return blocks


def _handle_extract_line_numbers_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pull marginal verse line numbers out of the target blocks.

    Uses `FusionAgent.process_extract_line_numbers`, which is the supported entry
    point: `docstruct.fusion.line_numbers.extract_line_numbers` needs a block list
    plus a stats counter and a provenance tag, so calling it with a plain string
    raised `TypeError` on every step.

    The numbers leave the element text and stay in ``metadata["line_numbers"]``,
    where the structured payload exposes them; every target keeps its id and
    provenance, so obligations and observations that point at it stay valid.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    agent = _fusion_agent()
    extracted = 0
    changed = 0
    for element in elements:
        result = agent.process_extract_line_numbers(
            _element_blocks([element], manifest)
        )
        blocks = result.get("blocks") or []
        source = blocks[0] if blocks else None
        numbers = [
            str(block.get("text") or "")
            for block in blocks
            if block.get("type") == "line_number"
        ]
        if not numbers or not isinstance(source, dict) or not source.get("verse_nums"):
            continue
        element.text = str(source.get("md") or "")
        element.metadata["line_numbers"] = numbers
        element.metadata["verse_nums"] = True
        extracted += len(numbers)
        changed += 1

    if not extracted:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_LINE_NUMBERS_NONE),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_LINE_NUMBERS_EXTRACTED, extracted).format(
            count=extracted,
            blocks=n(*MSG_BLOCK_COUNT, changed).format(count=changed),
        ),
    )


def _split_verse_element(
    element: ManifestElement,
    manifest: ProcessingManifest,
    known_ids: set[str],
) -> list[ManifestElement] | None:
    """``element`` as one manifest element per verse chunk, or ``None``.

    The first chunk keeps the source id, so obligations and observations that
    point at the element keep working; the other chunks get suffixed ids and
    carry ``split_from``, ``verse`` and their position in the split.
    """
    result = _fusion_agent().process_chunk_verse(
        _element_blocks([element], manifest)
    )
    blocks = result.get("blocks") or []
    if len(blocks) <= 1:
        return None

    chunks = [str(block.get("md") or "") for block in blocks]
    provenance = split_provenance(
        element, [chunk.count("\n") + 1 for chunk in chunks]
    )
    count = len(chunks)
    parts: list[ManifestElement] = []
    for index, chunk in enumerate(chunks):
        metadata = deepcopy(element.metadata)
        metadata.update(
            {"verse": True, "chunk_index": index, "chunk_count": count}
        )
        source_provenance = provenance[index] if index < len(provenance) else []
        if index == 0:
            element.text = chunk
            element.metadata = metadata
            element.provenance = source_provenance
            parts.append(element)
            continue
        metadata["split_from"] = element.id
        parts.append(
            element.model_copy(
                deep=True,
                update={
                    "id": unique_element_id(
                        f"{element.id}-verse-{index}", known_ids
                    ),
                    "text": chunk,
                    "provenance": source_provenance,
                    "metadata": metadata,
                },
            )
        )
    return parts


def _handle_chunk_verse_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Split verse/record blocks into chunks the evaluator can re-group.

    `docstruct.fusion.verse.chunk_verse` takes already-split lines plus a character
    budget, so the handler goes through `FusionAgent.process_chunk_verse`, which
    detects the verse lines itself.

    The chunks replace the target in the manifest instead of only being counted:
    the first keeps the source id and the others become new elements, so the
    payload and the reading order show the split.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    known_ids = {element.id for element in manifest.elements}
    replacements: dict[str, list[ManifestElement]] = {}
    expansion: dict[str, list[str]] = {}
    split_blocks = 0
    chunks = 0
    for element in elements:
        parts = _split_verse_element(element, manifest, known_ids)
        if parts is None:
            continue
        replacements[element.id] = parts
        expansion[element.id] = [part.id for part in parts]
        split_blocks += 1
        chunks += len(parts)

    if not split_blocks:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_VERSE_NONE),
        )
    replace_elements(manifest, replacements)
    remap_references(manifest, expansion)
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_VERSE_SPLIT, chunks).format(
            count=chunks,
            blocks=n(*MSG_BLOCK_COUNT, split_blocks).format(count=split_blocks),
        ),
    )


class _FurnitureView:
    """A manifest element as ``page_number_position`` reads it.

    ``box`` is computed when read, so only the page-number furniture pays for
    ``_element_bbox``.
    """

    def __init__(self, element: ManifestElement, manifest: ProcessingManifest) -> None:
        self._element = element
        self._manifest = manifest

    @property
    def role(self) -> str | None:
        return element_role(self._element)

    @property
    def md(self) -> str:
        return self._element.text or ""

    @property
    def box(self) -> tuple[float, float, float, float] | None:
        return _element_bbox(self._element, self._manifest)


def _tailjoin_position(
    manifest: ProcessingManifest,
    elements: list[ManifestElement] | None = None,
) -> str | None:
    """Vertical position ("top"/"bot") of the page number in ``elements``.

    `join_tail` only applies the position-conditioned `tj3` rule when it knows
    where the page number sits, which is the distinction between `tailjoin` and
    `tailjoin-positioned`. Pagination is a page property, so the handler passes
    one page's elements and callers that omit them read the whole manifest.
    """
    return page_number_position(
        _FurnitureView(element, manifest)
        for element in (manifest.elements if elements is None else elements)
    )


#: Element types the tail join leaves out, matching what the builder sends it.
_TAILJOIN_EXCLUDED_TYPES = frozenset({"formula", "table", "picture"})


def _handle_tailjoin_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Join the trailing short blocks (header/footer/page number).

    `docstruct.fusion.tailjoin.join_tail` requires the tail mode, a maximum short
    block length and the number of blocks to consider, so it cannot be called with
    the text alone. `FusionAgent.process_join_tail` supplies those defaults.

    The join runs over the whole page, not only over the obligation targets: the
    primitive needs the block before the tail to recognize it. The joined text
    lands on the first tail element, the others leave the manifest and the
    payload, and every reference to a dropped id moves to the survivor.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    target_ids = {element.id for element in elements}
    agent = _fusion_agent()
    pages: dict[int | None, list[ManifestElement]] = {}
    for element in elements:
        pages.setdefault(element.page_number, []).append(element)

    replacements: dict[str, list[ManifestElement]] = {}
    dropped: dict[str, list[str]] = {}
    pending: list[tuple[ManifestElement, str, list[ManifestElement]]] = []
    before_count = 0
    after_count = 0
    for page_number in pages:
        page_elements = sorted(
            (
                element
                for element in manifest.elements
                if element.page_number == page_number
                and element.text
                and element.type not in _TAILJOIN_EXCLUDED_TYPES
            ),
            key=lambda element: element.reading_order,
        )
        texts = [element.text or "" for element in page_elements]
        if len(texts) < 2:
            continue
        merged = agent.process_join_tail(
            texts,
            position=_tailjoin_position(manifest, page_elements),
        )
        if len(merged) >= len(texts):
            continue
        # `join_tail` only merges the trailing blocks, so the survivor is the
        # first one of the merged tail and everything after it is gone.
        survivor = page_elements[len(merged) - 1]
        removed = page_elements[len(merged):]
        removed_ids = {element.id for element in removed}
        if survivor.id not in target_ids or not removed_ids <= target_ids:
            return MethodResult(
                success=False,
                validated=False,
                message=t(MSG_TAILJOIN_MISMATCH).format(
                    survivor=survivor.id, removed=sorted(removed_ids)
                ),
            )
        pending.append((survivor, merged[-1], removed))
        before_count += len(texts)
        after_count += len(merged)

    if not pending:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_TAILJOIN_NONE),
        )
    # Every page is validated before anything changes, so a mismatch on a later
    # page never leaves an earlier one half-joined.
    for survivor, joined_text, removed in pending:
        tail = [survivor, *removed]
        provenance = joined_provenance(tail, joined_text)
        survivor.text = joined_text
        survivor.provenance = provenance
        survivor.metadata["tailjoined"] = True
        survivor.metadata["tailjoin_sources"] = sorted(
            element.id for element in removed
        )
        for element in removed:
            replacements[element.id] = []
            dropped[element.id] = [survivor.id]

    replace_elements(manifest, replacements)
    remap_references(manifest, dropped)
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_TAILJOIN_JOINED, after_count).format(
            before=before_count, after=after_count, pages=len(pending)
        ),
    )


def _handle_deterministic_heading_repair_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Repair the full sequence, since fixing one heading can expose a later gap."""
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)

    targets = _target_elements(manifest, obligation_id)
    if not targets or any(element.type not in {"title", "heading"} for element in targets):
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_HEADING_NONE),
        )
    previous = 0
    repaired = 0
    for element in sorted(manifest.elements, key=lambda item: item.reading_order):
        if element.type not in {"title", "heading"}:
            continue
        level = 1 if not previous else max(2, min(element.hierarchy_level, previous + 1, 6))
        if previous and element.type == "title":
            element.metadata["original_type"] = "title"
            element.type = "heading"
        if level != element.hierarchy_level:
            element.metadata["original_heading_level"] = element.hierarchy_level
            element.hierarchy_level = level
            element.metadata["heading_repaired"] = True
            repaired += 1
        previous = level
    manifest.summary.element_types = dict(Counter(element.type for element in manifest.elements))
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_HEADING_REPAIRED, repaired).format(count=repaired),
    )
