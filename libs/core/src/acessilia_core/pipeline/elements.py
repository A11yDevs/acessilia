"""Manifest elements as the payload's blocks, their boxes, and the table checks.

Moved verbatim from the PDDL orchestrator (#402, phase 3, step 6). The payload,
the handlers, the furniture checks and the enrichment stages read them.

``_table_ast_from_metadata`` and ``_table_element_has_structured_content``
delegate their structural rules to ``docstruct.tables.structured`` (#612),
passing the core's localized placeholder label explicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docstruct.blocks.lists import (
    marker_numbering,
)
from docstruct.geometry import OrientedBox
from docstruct.tables.ast import (
    raw_rows_from_table_ast as _rows_from_table_ast,
    table_ast_from_rows,
)
from docstruct.tables.structured import (
    normalize_strict_table_ast,
    table_ast_has_structured_content,
)
from docstruct.text.code_reflow import normalize_code_text

from acessilia_core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from acessilia_core.i18n import t

if TYPE_CHECKING:
    pass


#: Canonical English msgid for the alt text of a picture the vision model left
#: undescribed; why it was left so goes to the operator, not the reader.
MSG_UNDESCRIBED_PICTURE_ALT: str = "Image without a text description."


def _element_bbox(
    element: ManifestElement,
    manifest: ProcessingManifest,
) -> tuple[float, float, float, float] | None:
    """Element bounding box normalized to the unit page expected by docstruct."""
    for item in element.provenance:
        box = getattr(item, "bbox", None)
        if box is None:
            continue
        page = next(
            (
                page
                for page in manifest.pages
                if page.page_number == item.page_number
            ),
            None,
        )
        if page is None:
            return None
        return OrientedBox(
            box.left, box.top, box.right, box.bottom, box.coord_origin
        ).page_fractions(page.width, page.height)
    return None


#: The single cell of a table that reached the payload with no text. It is
#: written by _element_to_block and passed to ``table_ast_has_structured_content``,
#: which must keep agreeing; the reader sees it, in Portuguese (#410).
_TABLE_PLACEHOLDER_TEXT = "Tabela detectada"


def _text_kept_by_picture(element: ManifestElement) -> list[ManifestElement]:
    """The text a picture took from the slide, as paragraphs, when it went undescribed.

    Slide structuring hands text to a picture: a slide read as one picture
    keeps the text it replaced (``replaced_text``), a text slide's labels are
    folded into the picture they lie on or beside (``figure_labels``). Its
    description was to carry that text; without one, the text goes back to
    the slide after the picture, as it stood before, instead of being lost or
    listed as the picture's alt text (006.pdf v5, slides 16 and 31).

    Only the vision model's description carries that text: an alt the
    extractor gave the picture, which a failed call leaves in place, does not.
    The paragraphs carry the picture's source location; the labels' own boxes
    left with the elements they were folded from.
    """
    if element.type != "picture" or (
        element.metadata.get("vision_description_complete") and (element.text or "").strip()
    ):
        return []
    replaced = element.metadata.get("replaced_text")
    texts = (
        [line for line in replaced.splitlines() if line.strip()]
        if isinstance(replaced, str) and replaced.strip()
        else list(element.metadata.get("figure_labels") or [])
    )
    return [
        ManifestElement(
            id=f"{element.id}-kept-{index:03d}",
            type="paragraph",
            raw_label="paragraph",
            reading_order=element.reading_order,
            hierarchy_level=element.hierarchy_level,
            text=text,
            page_number=element.page_number,
            provenance=list(element.provenance),
            metadata={"kept_from_undescribed_picture": element.id},
        )
        for index, text in enumerate(texts, start=1)
    ]


def _element_to_block(
    element: ManifestElement, callout_titles: dict[str, str] | None = None
) -> dict[str, Any]:
    provenance = element.provenance[0] if element.provenance else None
    metadata: dict[str, Any] = {
        "raw_label": element.raw_label,
        "source_ref": element.source_ref,
        "parent_id": element.parent_id,
        "confidence": element.confidence,
        "manifest_element_id": element.id,
    }
    if element.metadata:
        metadata.update(element.metadata)
    metadata = _normalize_metadata_links(metadata)

    source_location: dict[str, Any] = {}
    if provenance is not None:
        source_location["page_number"] = provenance.page_number
        if provenance.bbox is not None:
            source_location["bbox"] = {
                "left": provenance.bbox.left,
                "top": provenance.bbox.top,
                "right": provenance.bbox.right,
                "bottom": provenance.bbox.bottom,
            }

    text = element.text or ""
    callout_id = metadata.get("callout_id")
    callout_role = str(metadata.get("callout_role", "")).lower()
    callout_type = str(metadata.get("callout_type", "note")).lower()
    callout_title = (callout_titles or {}).get(str(callout_id)) or str(
        metadata.get("callout_title", "")
    ).strip()
    callout_block_type = "warning" if callout_type in {"warning", "aviso", "importante", "caution"} else "note"
    block: dict[str, Any] = {
        "id": element.id,
        "source_location": source_location,
        "metadata": metadata,
    }

    if (
        callout_id
        and callout_role != "title"
        and metadata.get("slide_role") not in {"slide_heading", "deck_title"}
    ):
        block.update(
            {
                "type": callout_block_type,
                "title": callout_title,
                "text": text,
            }
        )
        return block

    if element.type in {"title", "heading"}:
        block.update(
            {
                "type": "heading",
                "level": 1 if element.type == "title" else max(1, element.hierarchy_level),
                "text": text or element.raw_label,
            }
        )
    elif element.type == "list_item":
        ordered = bool(metadata.get("enumerated"))
        block.update(
            {
                "type": "list",
                "ordered": ordered,
                "items": [text] if text else [],
            }
        )
        numbering = marker_numbering(metadata.get("marker")) if ordered else None
        if numbering is not None:
            start, style = numbering
            if start > 1:
                block["start"] = start
            if style != "decimal":
                block["numbering"] = style
    elif element.type == "table":
        table_ast = _table_ast_from_metadata(metadata)
        rows = _rows_from_table_ast(table_ast) if table_ast else None
        if not rows:
            rows = [[text]] if text else [[_TABLE_PLACEHOLDER_TEXT]]
            if table_ast is None:
                table_ast = table_ast_from_rows(rows)
        block.update(
            {
                "type": "table",
                "rows": rows,
                "table_ast": table_ast,
            }
        )
    elif element.type == "picture":
        block.update(
            {
                "type": "image",
                "alt_text": text or t(MSG_UNDESCRIBED_PICTURE_ALT),
            }
        )
    elif element.type == "code":
        block.update({"type": "code", "text": normalize_code_text(text)})
    elif element.type == "formula":
        if text:
            block.update({"type": "math", "text": text})
        else:
            block.update({"type": "paragraph", "text": "Formula detectada."})
    else:
        block.update({"type": "paragraph", "text": text or element.raw_label})

    return block


def _normalize_metadata_links(metadata: dict[str, Any]) -> dict[str, Any]:
    def normalize_value(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("#/"):
            return value[1:]
        if isinstance(value, list):
            return [normalize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize_value(item) for key, item in value.items()}
        return value

    return {key: normalize_value(value) for key, value in metadata.items()}


def _table_ast_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    # Stricter than the isinstance(span, int) rule it replaces: a rowspan or
    # colspan carrying a JSON boolean is dropped (docstruct 0.5.7, #612).
    return normalize_strict_table_ast(metadata.get("table_ast"))


#: Slack, in PDF points, when finding the element a negation slash lies in.
_OVERLAY_HOST_TOLERANCE = 1.5


def _bbox(element: ManifestElement, page: int | None = None) -> tuple[int, Any] | None:
    """``(page, box)`` of the element: on ``page`` when given, else the first boxed one.

    An element can carry provenances on more than one page; a slash is only
    compared with the part of an element that lies on the slash's own page.
    """
    for provenance in element.provenance or []:
        if provenance.bbox is not None and page in (None, provenance.page_number):
            return provenance.page_number, provenance.bbox
    return None


def _table_element_has_structured_content(element: ManifestElement) -> bool:
    metadata = element.metadata or {}
    return table_ast_has_structured_content(
        metadata.get("table_ast"), placeholder=_TABLE_PLACEHOLDER_TEXT
    )
