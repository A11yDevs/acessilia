"""Deterministic handlers that repair text in place.

Unicode and negation-overlay repair, normalization, the repetition guard, line
numbers, verse chunking, tail joins and the heading hierarchy. None calls a
model or the Toolbox. Moved verbatim from the PDDL orchestrator (#402, phase 3,
step 6); ``handlers/registry.py``'s ``METHOD_HANDLERS`` registers them.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from docstruct.fusion.noise import (
    element_role,
)
from docstruct.fusion.tailjoin import page_number_position
from docstruct.sections import repair_heading_levels
from docstruct.text.norm_fix import norm_fix

from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from acessilia_core.pipeline.elements import (
    _element_bbox,
)
from acessilia_core.pipeline.handlers.common import (
    _fusion_agent,
    _missing_obligation,
    _target_elements,
)
from acessilia_core.pipeline.handlers.messages import (
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
    MSG_VERSE_NONE,
    MSG_VERSE_SPLIT,
)
from acessilia_core.pipeline.handlers.structure import (
    joined_provenance,
    remap_references,
    replace_elements,
    split_provenance,
    unique_element_id,
)
from acessilia_core.pipeline.handlers.unicode_repair import (  # noqa: F401
    _UNICODE_REPAIR_BLOCK_TYPES,
    _UNICODE_STANDALONE_SPACING_MIN,
    _compose_in_host,
    _handle_unicode_repair_method,
    _reattach_negation_overlays,
    _repair_table_cells,
)


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


@dataclass(frozen=True)
class _TailJoinPlan:
    survivor: ManifestElement
    joined_text: str
    removed: list[ManifestElement]
    before_count: int
    after_count: int


def _plan_page_tailjoin(
    manifest: ProcessingManifest,
    page_number: int | None,
    *,
    target_ids: set[str],
    agent: Any,
) -> tuple[_TailJoinPlan | None, MethodResult | None]:
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
        return None, None
    merged = agent.process_join_tail(
        texts,
        position=_tailjoin_position(manifest, page_elements),
    )
    if len(merged) >= len(texts):
        return None, None
    # `join_tail` only merges the trailing blocks, so the survivor is the
    # first one of the merged tail and everything after it is gone.
    survivor = page_elements[len(merged) - 1]
    removed = page_elements[len(merged) :]
    removed_ids = {element.id for element in removed}
    if survivor.id not in target_ids or not removed_ids <= target_ids:
        return None, MethodResult(
            success=False,
            validated=False,
            message=t(MSG_TAILJOIN_MISMATCH).format(
                survivor=survivor.id, removed=sorted(removed_ids)
            ),
        )
    return (
        _TailJoinPlan(
            survivor=survivor,
            joined_text=merged[-1],
            removed=removed,
            before_count=len(texts),
            after_count=len(merged),
        ),
        None,
    )


def _apply_tailjoin_plans(
    manifest: ProcessingManifest, plans: list[_TailJoinPlan]
) -> None:
    replacements: dict[str, list[ManifestElement]] = {}
    dropped: dict[str, list[str]] = {}
    for plan in plans:
        tail = [plan.survivor, *plan.removed]
        provenance = joined_provenance(tail, plan.joined_text)
        plan.survivor.text = plan.joined_text
        plan.survivor.provenance = provenance
        plan.survivor.metadata["tailjoined"] = True
        plan.survivor.metadata["tailjoin_sources"] = sorted(
            element.id for element in plan.removed
        )
        for element in plan.removed:
            replacements[element.id] = []
            dropped[element.id] = [plan.survivor.id]
    replace_elements(manifest, replacements)
    remap_references(manifest, dropped)


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
    page_numbers = list(dict.fromkeys(element.page_number for element in elements))

    plans: list[_TailJoinPlan] = []
    for page_number in page_numbers:
        plan, failure = _plan_page_tailjoin(
            manifest, page_number, target_ids=target_ids, agent=agent
        )
        if failure is not None:
            return failure
        if plan is not None:
            plans.append(plan)

    if not plans:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_TAILJOIN_NONE),
        )
    # Every page is validated before anything changes, so a mismatch on a later
    # page never leaves an earlier one half-joined.
    _apply_tailjoin_plans(manifest, plans)
    before_count = sum(plan.before_count for plan in plans)
    after_count = sum(plan.after_count for plan in plans)
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_TAILJOIN_JOINED, after_count).format(
            before=before_count, after=after_count, pages=len(plans)
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
    headings = [
        element
        for element in sorted(manifest.elements, key=lambda item: item.reading_order)
        if element.type in {"title", "heading"}
    ]
    repaired_levels = repair_heading_levels(
        [element.hierarchy_level for element in headings]
    )
    repaired = 0
    for index, (element, level) in enumerate(zip(headings, repaired_levels, strict=True)):
        if index > 0 and element.type == "title":
            element.metadata["original_type"] = "title"
            element.type = "heading"
        if level != element.hierarchy_level:
            element.metadata["original_heading_level"] = element.hierarchy_level
            element.hierarchy_level = level
            element.metadata["heading_repaired"] = True
            repaired += 1
    manifest.summary.element_types = dict(Counter(element.type for element in manifest.elements))
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_HEADING_REPAIRED, repaired).format(count=repaired),
    )
