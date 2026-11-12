"""The structured payload of a processed document: pages, blocks and metadata.

``build_pddl_structured_payload`` turns the executed manifest into what the
service and the exporters read. Moved verbatim from the PDDL orchestrator
(#402, phase 3, step 6).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docstruct.blocks.callouts import callout_titles
from docstruct.blocks.callouts import dedupe_callout_titles as _dedupe_callout_titles
from docstruct.blocks.lists import (
    merge_list_blocks,
    recover_empty_lettered_list_items,
)
from docstruct.export.page_text import blocks_text, pages_text
from docstruct.fusion.noise import (
    PAGE_NUMBER_MARGIN,
    element_role,
    is_bare_page_number,
    is_decorated_page_number,
    is_page_number_in_margin,
    select_page_numbers,
)
from docstruct.geometry import reading_role
from docstruct.regions.letterhead import PlacedItem, letterhead_groups

from backend.core.execution.models import ExecutionReport
from backend.core.manifest.builder import (
    is_unstructured_page_placeholder,
)
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from backend.core.planning.models import NominalPlan, PlanningComparison
from backend.i18n import locale_for_user, n, reset_request_locale, set_request_locale, t
from backend.log_messages import (
    LOG_PDDL_EMPTY_LIST_ITEMS_DROPPED,
    MSG_STRUCTURAL_EXTRACTION_DEGRADED,
)
from backend.tools.logger import logger
from backend.core.pipeline.obligations import (
    _unsatisfied_obligations,
    _unsatisfied_summary,
)
from backend.core.pipeline.elements import (
    _element_bbox,
    _element_to_block,
    _text_kept_by_picture,
)

if TYPE_CHECKING:
    pass


#: Canonical English msgid for an institutional header read as one paragraph:
#: the logo, then its header lines; {lines} is substituted by callers after lookup.
MSG_LETTERHEAD_TEXT: str = "Logo. {lines}."


#: Canonical English singular/plural msgids for the document's warning on the
#: pictures and tables a failure left without a description or a reading.
MSG_PICTURES_NOT_DESCRIBED: tuple[str, str] = (
    "{count} image could not be described.",
    "{count} images could not be described.",
)


MSG_TABLES_NOT_READ: tuple[str, str] = (
    "{count} table could not be read.",
    "{count} tables could not be read.",
)


def build_pddl_structured_payload(
    *,
    file_path: Path,
    manifest: ProcessingManifest,
    plan: NominalPlan,
    planner_backend: str,
    execution_report: ExecutionReport | None,
    comparison: PlanningComparison | None,
    toolbox_availability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pages_payload = _manifest_pages_to_payload(manifest)
    text_output = pages_text(pages_payload)
    configuration = manifest.extractor.configuration
    media_inspection_status = configuration.get("media_inspection")
    fusion_status = configuration.get("fusion") or {}
    unsatisfied_obligations = _unsatisfied_obligations(manifest)

    technical_warnings: list[str] = []
    if execution_report is None:
        technical_warnings.append(
            "Executor nao foi executado; somente manifesto e plano foram gerados."
        )
    elif execution_report.status in {
        "failed", "replan-required",
    } or unsatisfied_obligations:
        # A replan that leaves an exhausted refinement out can still report
        # `completed`; the open obligation must reach the document anyway. The
        # ids are in `pddl_unsatisfied_obligations`, so the warning stays short.
        technical_warnings.append(_unsatisfied_summary(manifest))

    if comparison is not None:
        technical_warnings.append(
            f"Comparacao de planners: {comparison.comparison.verdict}."
        )

    visual_failures = _visual_failures(manifest)
    for kind, msgids in (("pictures", MSG_PICTURES_NOT_DESCRIBED), ("tables", MSG_TABLES_NOT_READ)):
        if count := sum((visual_failures or {}).get(kind, {}).values()):
            technical_warnings.append(n(*msgids, count).format(count=count))

    observations = getattr(manifest, "observations", [])
    obligations = getattr(manifest, "obligations", [])
    if any(
        observation.kind == "repair-legacy-unicode-detected"
        for observation in observations
    ) and not any(
        obligation.kind == "repair-legacy-unicode"
        for obligation in obligations
    ):
        # Only the observation exists: LEGACY_UNICODE_REPAIR=detect. The
        # warning names the switch because the job delivers the text as
        # extracted, NFD and dotless-i included.
        technical_warnings.append(
            "Texto com sinais de Unicode legado (NFD, i sem ponto ou acento espaçador); "
            "reparo desabilitado (LEGACY_UNICODE_REPAIR=detect)."
        )

    extraction_degraded = records_extraction_degradation(
        configuration.get("extraction_degraded")
    )
    if extraction_degraded:
        technical_warnings.append(
            t(MSG_STRUCTURAL_EXTRACTION_DEGRADED).format(
                provider=configuration.get("toolbox_provider", manifest.extractor.name)
            )
        )

    return {
        "text": text_output,
        "pages": pages_payload,
        "page_count": len(pages_payload),
        "mode": f"pddl-{planner_backend}",
        "source_path": str(file_path),
        "canonical_metadata": {
            "pipeline_engine": "pddl",
            "pddl_validation_only": True,
            "accessibility_verified": False,
            "pddl_manifest_id": manifest.manifest_id,
            "pddl_manifest_revision": manifest.revision,
            "pddl_plan_id": plan.plan_id,
            "pddl_planner": plan.planner,
            "pddl_expected_total_cost": plan.expected_total_cost,
            "pddl_execution_id": execution_report.execution_id
            if execution_report
            else None,
            "pddl_execution_status": execution_report.status
            if execution_report
            else None,
            "pddl_comparison_verdict": comparison.comparison.verdict
            if comparison
            else None,
            "pddl_unsatisfied_obligations": unsatisfied_obligations,
            # The open obligations a delivered document still has, for the
            # result e-mail: the job page and e-mail show no technical warning.
            "pddl_unsatisfied_summary": _unsatisfied_summary(manifest)
            if unsatisfied_obligations
            else None,
            "pddl_toolbox_availability": toolbox_availability,
            "pddl_fusion": fusion_status or None,
            **(
                {
                    "pddl_extraction_degraded": True,
                    "pddl_extraction_failures": configuration.get("extraction_failures", {}),
                }
                if extraction_degraded else {}
            ),
            # Pictures and tables left undescribed or unread, by reason; a rerun
            # once the model provider or the Toolbox is back may deliver them.
            "pddl_visual_failures": visual_failures,
            "pddl_media_inspection": {
                "status": media_inspection_status,
                "error": configuration.get("media_inspection_error"),
                # Why a deck was structured slide by slide (or not).
                "document_genre": configuration.get("document_genre"),
                "genre_signals": configuration.get("genre_signals", []),
            }
            if media_inspection_status is not None
            else None,
        },
        "technical_warnings": technical_warnings,
        # A step degraded by a Toolbox or model failure must not be replayed
        # from the cache once the service is back.
        "cacheable": (
            media_inspection_status != "failed"
            and fusion_status.get("status") != "degraded"
            and execution_report is not None
            and execution_report.status in {"completed", "dry-run-completed"}
            and not any(
                item["recovery"] != "human-review" for item in unsatisfied_obligations
            )
            and not records_visual_failures(visual_failures)
            and not extraction_degraded
        ),
    }


#: Why a picture or table left without a description or a reading may come
#: out differently on a rerun: the model provider or the Toolbox was down, or
#: the extraction embedded no image in a pageless picture (a Toolbox that
#: forwards it would get the picture described). An
#: empty description is the model's answer, as is a refused table reading, and
#: would come back the same, so it neither counts nor keeps a run uncached.
_RETRYABLE_VISUAL_FAILURES = frozenset(
    {"crop_unavailable", "image_unavailable", "model_failed"}
)


def _visual_failures(manifest: ProcessingManifest) -> dict[str, dict[str, int]] | None:
    """Pictures left undescribed and tables left unread, counted by reason.

    A picture counts whatever its type: the vision stage also describes the
    placeholders of a mostly visual document, and an element becomes a
    ``picture`` only once the model answers. None when nothing failed.
    """
    elements = getattr(manifest, "elements", [])
    counts = {
        "pictures": Counter(
            reason for element in elements
            if (reason := element.metadata.get("vision_failure_reason")) in _RETRYABLE_VISUAL_FAILURES
        ),
        "tables": Counter(
            reason for element in elements
            if (reason := element.metadata.get("table_read_failure")) in _RETRYABLE_VISUAL_FAILURES
        ),
    }
    failures = {kind: dict(by_reason) for kind, by_reason in counts.items() if by_reason}
    return failures or None


def records_visual_failures(failures: Any) -> bool:
    """Whether ``canonical_metadata.pddl_visual_failures`` records any failure.

    A run that does is not cached, and a cached entry that does is not
    replayed; both sides read the record through this one check.
    """
    return isinstance(failures, dict) and any(
        isinstance(by_reason, dict)
        and any(isinstance(count, int) and count > 0 for count in by_reason.values())
        for by_reason in failures.values()
    )


def records_extraction_degradation(flag: Any) -> bool:
    """Whether the structural extraction came from one provider of a dual run.

    ``flag`` is the extractor's ``extraction_degraded`` or, on a cached entry,
    ``canonical_metadata.pddl_extraction_degraded``. A run that records it is
    not cached, and a cached entry that does is not replayed.
    """
    return flag is True


def _is_left_out_of_payload(element: ManifestElement) -> bool:
    """A page accepted as blank, or a placeholder not yet inspected, adds nothing.

    Nor does a detached negation slash: it was given back to its relation, or
    could not be, and alone it says nothing to a reader.

    An inspected page with content is a ``picture``, no longer a placeholder.
    A placeholder still present means the inspection did not run (dry-run), so
    the page contributes no block rather than its raw label.
    """
    return (
        bool(element.metadata.get("blank_page"))
        or bool(element.metadata.get("negation_overlay"))
        or is_unstructured_page_placeholder(element)
    )


#: Types a page number can arrive as. A number inside a table, list, heading
#: or formula is content, wherever it sits on the page.
_PAGE_NUMBER_TYPES = frozenset({"paragraph", "page_header", "page_footer", "unknown"})


def _is_marked_furniture(element: ManifestElement) -> bool:
    """Whether the extractor marked ``element`` as page header/footer.

    Read from the type, the raw label (an element typed ``paragraph`` may keep
    ``page_footer`` there) or Docling's ``content_layer``.
    """
    return (
        element_role(element) in {"header", "footer", "page_number"}
        or reading_role(str(element.type), str(element.raw_label)) != "body"
        or element.metadata.get("content_layer") == "furniture"
    )


def _page_number_ids(manifest: ProcessingManifest) -> set[str]:
    """Elements that are page numbers rather than body text.

    A screen reader would announce them in the middle of the text. A number
    the extractor marked as furniture is one. Otherwise only its position in
    the top or bottom margin tells it apart from a number of the body, and a
    page has one page number: the margin decides only on a page without a
    marked one and with a single candidate, so chart axis labels or a footnote
    marker next to the page number stay. The rules are docstruct's
    (``docstruct.fusion.noise``); this reads the manifest's elements for them.
    """
    candidates: list[tuple[str, int, bool]] = []
    for element in manifest.elements:
        if element.type not in _PAGE_NUMBER_TYPES:
            continue
        page = element.page_number or 1
        if _is_marked_furniture(element):
            if is_decorated_page_number(element.text or ""):
                candidates.append((element.id, page, True))
        elif is_bare_page_number(element.text) and is_page_number_in_margin(
            # The text is checked first: finding the box searches the pages.
            element.text, _element_bbox(element, manifest)
        ):
            candidates.append((element.id, page, False))
    return select_page_numbers(candidates)


def _is_page_header_line(
    element: ManifestElement, bbox: tuple[float, ...]
) -> bool:
    """A non-empty line the extractor marked as page header.

    Read from the type and raw label, like the page number filter. Docling's
    ``content_layer`` does not tell header from footer, so a ``furniture``
    line counts only in the top margin.
    """
    if not (element.text or "").strip():
        return False
    if (
        element_role(element) == "header"
        or reading_role(str(element.type), str(element.raw_label)) == "header"
    ):
        return True
    return (
        element.metadata.get("content_layer") == "furniture"
        and (bbox[1] + bbox[3]) / 2 < PAGE_NUMBER_MARGIN
    )


def _letterhead_groups(
    manifest: ProcessingManifest, page_numbers: set[str]
) -> dict[str, list[ManifestElement]]:
    """Logos and the page header lines beside them, keyed by the first in reading order.

    The grouping is docstruct's ``letterhead_groups``; this reads the manifest
    for it: which elements reach the payload, which are header lines
    (:func:`_is_page_header_line`), and their boxes. A page header without a
    picture is left as is.
    """
    pictures: list[PlacedItem] = []
    lines: list[PlacedItem] = []
    elements: dict[str, ManifestElement] = {}
    for element in manifest.elements:
        if _is_left_out_of_payload(element) or element.id in page_numbers:
            continue
        bbox = _element_bbox(element, manifest)
        if bbox is None:
            continue
        item = PlacedItem(element.id, element.page_number or 1, element.reading_order, bbox)
        if element.type == "picture":
            pictures.append(item)
        elif _is_page_header_line(element, bbox):
            lines.append(item)
        else:
            continue
        elements[element.id] = element
    return {
        key: [elements[member] for member in members]
        for key, members in letterhead_groups(pictures, lines).items()
    }


def _letterhead_block(
    members: list[ManifestElement], language: str | None
) -> dict[str, Any]:
    """One paragraph for a logo and its header lines, in place of the first of them.

    The paragraph replaces the picture too: the outputs never showed the
    logo's pixels (Pandoc writes an image block as a paragraph of its alt
    text), only the description this paragraph stands for. The text is in
    the document's language, not the interface's. ``role`` and
    ``letterhead_members`` record the merge for audit; no renderer reads
    them, so the PDF/UA tag stays ``P``.
    """
    block = _element_to_block(members[0])
    lines = [
        (member.text or "").strip().rstrip(".,;")
        for member in members
        if member.type != "picture"
    ]
    token = set_request_locale(locale_for_user(language))
    try:
        template = t(MSG_LETTERHEAD_TEXT)
    finally:
        reset_request_locale(token)
    block["type"] = "paragraph"
    block["text"] = template.format(lines=", ".join(lines))
    block.pop("alt_text", None)
    block["metadata"]["role"] = "header"
    block["metadata"]["letterhead_members"] = [member.id for member in members]
    return block


def _manifest_pages_to_payload(manifest: ProcessingManifest) -> list[dict[str, Any]]:
    elements_by_id = {element.id: element for element in manifest.elements}
    page_numbers = _page_number_ids(manifest)
    letterheads = _letterhead_groups(manifest, page_numbers)
    #: Letterhead members other than the first, which carries the whole group.
    merged = {
        member.id
        for members in letterheads.values()
        for member in members[1:]
    }
    letterhead_blocks = {
        key: _letterhead_block(members, manifest.language)
        for key, members in letterheads.items()
    }
    pages: list[dict[str, Any]] = []

    if manifest.pages:
        sorted_pages = sorted(manifest.pages, key=lambda page: page.page_number)
        for page in sorted_pages:
            block_elements = [
                elements_by_id[element_id]
                for element_id in page.element_ids
                if element_id in elements_by_id
            ]
            if not block_elements:
                # Some extractors can fill in pages without element_ids; in that
                # case we fall back to page_number so no content is lost.
                block_elements = [
                    element
                    for element in manifest.elements
                    if (element.page_number or 1) == page.page_number
                ]
            block_elements = [
                item
                for item in block_elements
                if not _is_left_out_of_payload(item)
                and item.id not in page_numbers
                and item.id not in merged
            ]
            block_elements.sort(key=lambda item: item.reading_order)
            blocks = _elements_to_blocks(block_elements, letterhead_blocks)
            _dedupe_callout_titles(blocks)
            pages.append(
                {
                    "page_number": page.page_number,
                    "text": _render_text_from_blocks(blocks),
                    "blocks": blocks,
                }
            )
        return pages

    grouped: dict[int, list[ManifestElement]] = {}
    for element in manifest.elements:
        if (
            _is_left_out_of_payload(element)
            or element.id in page_numbers
            or element.id in merged
        ):
            continue
        page_number = element.page_number or 1
        grouped.setdefault(page_number, []).append(element)

    for page_number in sorted(grouped):
        page_elements = sorted(
            grouped[page_number],
            key=lambda item: item.reading_order,
        )
        blocks = _elements_to_blocks(page_elements, letterhead_blocks)
        _dedupe_callout_titles(blocks)
        pages.append(
            {
                "page_number": page_number,
                "text": _render_text_from_blocks(blocks),
                "blocks": blocks,
            }
        )

    return pages


def _elements_to_blocks(
    elements: list[ManifestElement], replacements: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Blocks of ``elements`` in order, with the text an undescribed picture held.

    An element in ``replacements`` (the first member of a letterhead) gives
    way to its block, which already stands for the picture's text.
    """
    titles = callout_titles(elements)
    recovered_items, consumed_text, preambles = _recover_empty_lettered_list_items(elements)
    blocks: list[dict[str, Any]] = []
    dropped_empty_items: list[ManifestElement] = []
    for element in elements:
        if element.id in replacements:
            blocks.append(replacements[element.id])
            continue
        if preamble := preambles.get(element.id):
            blocks.append(_element_to_block(preamble, titles))
        text = consumed_text.get(element.id)
        if text is not None:
            if not text:
                continue
            element = element.model_copy(update={"text": text})
        recovered = recovered_items.get(element.id)
        if recovered is not None:
            item_text, marker = recovered
            metadata = {**element.metadata, "enumerated": True, "marker": marker}
            element = element.model_copy(
                update={"text": item_text, "metadata": metadata}
            )
        block = _element_to_block(element, titles)
        if block.get("type") != "list" or any(
            isinstance(item, str) and item.strip()
            for item in block.get("items", [])
        ):
            blocks.append(block)
        else:
            dropped_empty_items.append(element)
        blocks.extend(_element_to_block(kept) for kept in _text_kept_by_picture(element))
    if dropped_empty_items:
        # The extractor found list items it could not read; the document
        # goes without them, which the operator should be able to see.
        logger.warning(
            t(LOG_PDDL_EMPTY_LIST_ITEMS_DROPPED).format(
                count=len(dropped_empty_items),
                page=dropped_empty_items[0].page_number,
                element_ids=", ".join(item.id for item in dropped_empty_items),
            )
        )
    return merge_list_blocks(blocks)


def _recover_empty_lettered_list_items(
    elements: list[ManifestElement],
) -> tuple[dict[str, tuple[str, str]], dict[str, str], dict[str, ManifestElement]]:
    """Recover a fully extracted lettered list from a sibling text element.

    The rule is docstruct's :func:`~docstruct.blocks.lists.recover_empty_lettered_list_items`.
    This adapter keeps the payload's shapes: item id -> (text, marker), source
    paragraph id -> remaining prefix, and first item id -> the preamble as a
    copy of its source element, emitted before that item.
    """
    recovery = recover_empty_lettered_list_items(elements)
    by_id = {element.id: element for element in elements}
    preambles = {
        item_id: by_id[source_id].model_copy(update={"text": text})
        for item_id, (source_id, text) in recovery.preambles.items()
    }
    return dict(recovery.items), dict(recovery.consumed), preambles


#: What the payload's text says for an image without alt text. It is shown to
#: the reader and fixed in Portuguese: localizing it is #410's work.
_IMAGE_WITHOUT_TEXT = "Imagem"


def _render_text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    """One page's plain text: docstruct's ``blocks_text`` with the core's words."""
    return blocks_text(blocks, image_text=_IMAGE_WITHOUT_TEXT)
