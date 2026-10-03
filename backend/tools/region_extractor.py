from __future__ import annotations

from typing import Any

import fitz

from docstruct.regions.grouping import (  # noqa: F401
    CALLOUT_MAX_VERTICAL_GAP,
    CALLOUT_MAX_WIDTH_RATIO,
    CALLOUT_MIN_GROUP_SIZE,
    CALLOUT_MIN_INDENT_PX,
    CALLOUT_MIN_INDENT_RATIO,
    LIST_LINE_PATTERNS,
    MONOSPACE_FONTS,
    _add_unknown_gaps,
    _estimate_main_text_band,
    ENABLE_PYMUPDF_CALLOUT_MERGE,
    _fill_gaps_with_unknown,
    _is_known_callout_title,
    _is_same_callout_cluster,
    _merge_bboxes,
    _normalize_text_key,
    _starts_with_list_marker,
)
from docstruct.types import Region

from backend.config.settings import settings


def _known_callout_titles() -> frozenset[str]:
    """Domain-specific callout titles from configuration (semicolon-separated)."""
    raw = settings.callout_known_titles.strip()
    if not raw:
        return frozenset()
    return frozenset(t.strip().lower() for t in raw.split(";") if t.strip())


def extract_regions(page: fitz.Page) -> list[Region]:
    regions: list[Region] = []
    page_num = page.number + 1

    image_map = _build_image_map(page)

    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get(
        "blocks", []
    )

    for block in blocks:
        bbox = tuple(block.get("bbox", (0, 0, 0, 0)))
        block_type = block.get("type")

        if block_type == 0:
            region = _text_block_to_region(block, bbox, page_num)
            if region and region.text.strip():
                regions.append(region)

        elif block_type == 1:
            region = _image_block_to_region(block, bbox, page_num, image_map)
            if region:
                regions.append(region)

    _fill_gaps_with_unknown(page, regions, page_num)

    if ENABLE_PYMUPDF_CALLOUT_MERGE:
        regions = _merge_callout_groups(regions, page.rect.width)

    regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
    return regions


def _build_image_map(page: fitz.Page) -> dict[int, dict[str, Any]]:
    image_map: dict[int, dict[str, Any]] = {}
    doc = page.parent
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        try:
            base = doc.extract_image(xref)
            if base and base.get("image"):
                image_map[xref] = base
        except Exception:
            pass
    return image_map


def _text_block_to_region(
    block: dict[str, Any],
    bbox: tuple[float, float, float, float],
    page_num: int,
) -> Region | None:
    lines = block.get("lines", [])
    if not lines:
        return None

    full_text = ""
    total_chars = 0
    font_sizes: list[float] = []
    all_monospace = True
    line_texts: list[str] = []

    for line in lines:
        spans = line.get("spans", [])
        line_text = ""
        for span in spans:
            text = span.get("text", "")
            line_text += text + " "
            full_text += text + " "
            total_chars += len(text)
            font_sizes.append(span.get("size", 0))
            font_name = span.get("font", "").lower()
            is_mono = any(mf in font_name for mf in MONOSPACE_FONTS)
            if not is_mono:
                all_monospace = False
        line_texts.append(line_text.strip())

    full_text = full_text.strip()

    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if area <= 0:
        return None

    text_density = total_chars / area if area > 0 else 0
    avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 0

    subtype = ""
    if all_monospace and total_chars >= 10:
        subtype = "code"
    elif line_texts and _starts_with_list_marker(line_texts[0]):
        subtype = "list"

    return Region(
        bbox=bbox,
        type="text",
        text=full_text,
        image_bytes=None,
        confidence=min(text_density * 50, 1.0),
        page_num=page_num,
        metadata={
            "total_chars": total_chars,
            "text_density": round(text_density, 4),
            "avg_font_size": round(avg_font_size, 1),
            "line_count": len(lines),
            "subtype": subtype,
        },
    )


def _merge_callout_groups(regions: list[Region], page_width: float) -> list[Region]:
    text_regions = [
        region
        for region in regions
        if region.type == "text"
        and region.text.strip()
        and region.metadata.get("subtype") not in {"code"}
    ]
    if len(text_regions) < CALLOUT_MIN_GROUP_SIZE:
        return regions

    main_left, main_right = _estimate_main_text_band(text_regions)
    band_width = main_right - main_left
    if band_width <= 0:
        return regions

    indent_threshold = max(
        CALLOUT_MIN_INDENT_PX,
        max(page_width, band_width) * CALLOUT_MIN_INDENT_RATIO,
    )

    candidates: list[Region] = []
    for region in sorted(text_regions, key=lambda item: (item.bbox[1], item.bbox[0])):
        left, top, right, bottom = region.bbox
        width = max(1.0, right - left)
        left_indent = left - main_left
        right_indent = main_right - right
        combined_indent = max(0.0, left_indent) + max(0.0, right_indent)
        if (
            max(left_indent, right_indent) < indent_threshold
            and combined_indent < (indent_threshold * 1.35)
        ):
            continue
        if width > band_width * CALLOUT_MAX_WIDTH_RATIO:
            continue
        if top >= bottom:
            continue
        candidates.append(region)

    if len(candidates) < CALLOUT_MIN_GROUP_SIZE:
        return regions

    groups: list[list[Region]] = []
    current: list[Region] = [candidates[0]]
    for region in candidates[1:]:
        previous = current[-1]
        if _is_same_callout_cluster(previous, region):
            current.append(region)
        else:
            groups.append(current)
            current = [region]
    groups.append(current)

    grouped_ids = {
        id(region)
        for group in groups
        if len(group) >= CALLOUT_MIN_GROUP_SIZE
        for region in group
    }
    result: list[Region] = [region for region in regions if id(region) not in grouped_ids]

    for index, group in enumerate(groups, start=1):
        sorted_group = sorted(group, key=lambda item: (item.bbox[1], item.bbox[0]))
        callout_title = _extract_callout_title(sorted_group[0])
        min_size = 2 if _is_known_callout_title(callout_title, _known_callout_titles()) else CALLOUT_MIN_GROUP_SIZE
        if len(group) < min_size:
            continue

        x0 = min(region.bbox[0] for region in sorted_group)
        y0 = min(region.bbox[1] for region in sorted_group)
        x1 = max(region.bbox[2] for region in sorted_group)
        y1 = max(region.bbox[3] for region in sorted_group)
        merged_text = "\n".join(region.text.strip() for region in sorted_group if region.text.strip())

        merged = Region(
            bbox=(x0, y0, x1, y1),
            type="text",
            text=merged_text,
            image_bytes=None,
            confidence=max(region.confidence for region in sorted_group),
            page_num=sorted_group[0].page_num,
            metadata={
                "total_chars": sum(int(region.metadata.get("total_chars", 0)) for region in sorted_group),
                "text_density": max(float(region.metadata.get("text_density", 0.0)) for region in sorted_group),
                "avg_font_size": max(float(region.metadata.get("avg_font_size", 0.0)) for region in sorted_group),
                "line_count": sum(int(region.metadata.get("line_count", 1)) for region in sorted_group),
                "subtype": "callout",
                "callout_id": f"callout-p{sorted_group[0].page_num}-{index}",
                "callout_type": "note",
                "callout_title": callout_title,
                "callout_source": "pymupdf-geometry",
            },
        )
        result.append(merged)

    return result


def _extract_callout_title(region: Region) -> str:
    text = region.text.strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    first_line = lines[0]
    if _is_known_callout_title(first_line, _known_callout_titles()):
        return first_line
    if len(first_line) <= 90 and int(region.metadata.get("line_count", 1)) <= 2:
        return first_line
    return ""


def _image_block_to_region(
    block: dict[str, Any],
    bbox: tuple[float, float, float, float],
    page_num: int,
    image_map: dict[int, dict[str, Any]],
) -> Region | None:
    width_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if width_area < 200:
        return None

    image_bytes: bytes | None = None
    for xref, img_data in image_map.items():
        img_w = img_data.get("width", 0)
        img_h = img_data.get("height", 0)
        page_area = width_area
        img_area = img_w * img_h

        if img_area > 0 and abs(page_area - img_area) / img_area < 0.5:
            image_bytes = img_data.get("image")
            break

    return Region(
        bbox=bbox,
        type="image",
        text="",
        image_bytes=image_bytes,
        confidence=0.9 if image_bytes else 0.3,
        page_num=page_num,
        metadata={"has_image_data": image_bytes is not None},
    )


def crop_region_to_image(
    page: fitz.Page, bbox: tuple[float, float, float, float], dpi: int = 200
) -> bytes:
    clip = fitz.Rect(bbox)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    return pix.tobytes("png")
