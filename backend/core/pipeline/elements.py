"""Manifest elements as the payload's blocks, their boxes, and the table checks.

Moved verbatim from the PDDL orchestrator (#402, phase 3, step 6). The payload,
the handlers, the furniture checks and the enrichment stages read them.

``_table_element_has_structured_content`` and ``_rows_look_like_placeholder``
tell a real table AST from the placeholder one; the table handler and the table
enrichment both use them. They live here for now: finding S of the orchestrator
inventory sends the row rule (``_rows_look_like_placeholder``) to
``docstruct.tables``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docstruct.blocks.lists import (
    marker_numbering,
)
from docstruct.tables.ast import (
    raw_rows_from_table_ast as _rows_from_table_ast,
)
from docstruct.text.code_reflow import normalize_code_text

from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
    is_bottom_left,
)
from backend.core.i18n import t

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
        if page is None or not page.width or not page.height:
            return None
        top, bottom = box.top, box.bottom
        if is_bottom_left(box.coord_origin, top, bottom):
            top, bottom = page.height - top, page.height - bottom
        return (
            box.left / page.width,
            top / page.height,
            box.right / page.width,
            bottom / page.height,
        )
    return None


#: The single cell of a table that reached the payload with no text. It is
#: written by _element_to_block and recognized by _rows_look_like_placeholder,
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
                table_ast = _table_ast_from_rows(rows)
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
    raw = metadata.get("table_ast")
    if not isinstance(raw, dict):
        return None

    table_ast: dict[str, Any] = {}
    caption = raw.get("caption")
    if isinstance(caption, str) and caption.strip():
        table_ast["caption"] = caption.strip()

    for section_name in ("header", "body", "footer"):
        section = raw.get(section_name)
        if not isinstance(section, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for row in section:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            normalized_cells: list[dict[str, Any]] = []
            for cell in cells:
                if not isinstance(cell, dict) or "text" not in cell:
                    continue
                text = str(cell.get("text", "")).strip()
                normalized_cell: dict[str, Any] = {"text": text}
                if isinstance(cell.get("header"), bool):
                    normalized_cell["header"] = cell["header"]
                scope = cell.get("scope")
                if isinstance(scope, str) and scope in {
                    "none",
                    "row",
                    "col",
                    "rowgroup",
                    "colgroup",
                }:
                    normalized_cell["scope"] = scope
                for span_key in ("rowspan", "colspan"):
                    span = cell.get(span_key)
                    if isinstance(span, int) and span >= 1:
                        normalized_cell[span_key] = span
                normalized_cells.append(normalized_cell)
            if normalized_cells:
                normalized_rows.append({"cells": normalized_cells})
        if normalized_rows:
            table_ast[section_name] = normalized_rows

    metadata_obj = raw.get("metadata")
    if isinstance(metadata_obj, dict):
        table_ast["metadata"] = metadata_obj

    return table_ast if table_ast.get("body") else None


def _table_ast_from_rows(rows: list[list[str]]) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = []
        for cell in row:
            text = str(cell).strip()
            cells.append({"text": text})
        if cells:
            body.append({"cells": cells})
    return {"body": body}


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
    table_ast = metadata.get("table_ast")
    if not isinstance(table_ast, dict):
        return False

    rows = _rows_from_table_ast(table_ast)
    if not rows:
        return False

    width = max((len(row) for row in rows), default=0)
    if len(rows) >= 2 and width >= 2:
        return True

    return not _rows_look_like_placeholder(rows)


def _rows_look_like_placeholder(rows: list[list[str]]) -> bool:
    if len(rows) != 1 or len(rows[0]) != 1:
        return False
    return rows[0][0].strip().lower() == _TABLE_PLACEHOLDER_TEXT.lower()
