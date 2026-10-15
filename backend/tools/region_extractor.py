from __future__ import annotations

import re
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
    _add_unknown_gaps as _shared_add_unknown_gaps,
    ENABLE_PYMUPDF_CALLOUT_MERGE,
    _is_known_callout_title,
    _merge_callout_groups as _shared_merge_callout_groups,
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

    blocks = page.get_text(
        "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_IMAGES
    ).get(
        "blocks", []
    )

    for block in blocks:
        bbox = tuple(fitz.Rect(block.get("bbox", (0, 0, 0, 0))) * page.rotation_matrix)
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


def _starts_with_list_marker(text: str) -> bool:
    stripped = text.strip()
    for pattern in LIST_LINE_PATTERNS:
        if stripped.startswith(pattern):
            return True
    # numbered list: "1." or "1)" but NOT "9.1" (section heading)
    if len(stripped) > 1 and stripped[0].isdigit() and stripped[1] in (".", ")"):
        if len(stripped) > 2 and stripped[2].isdigit():
            return False
        return True
    if (
        len(stripped) > 2
        and stripped[0].isalpha()
        and stripped[1] in (".", ")")
        and stripped[2] == " "
    ):
        return True
    return False


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
    return _shared_merge_callout_groups(regions, page_width, _known_callout_titles())


def _estimate_main_text_band(regions: list[Region]) -> tuple[float, float]:
    widths = [(region.bbox[0], region.bbox[2], region.bbox[2] - region.bbox[0]) for region in regions]
    if not widths:
        return (0.0, 0.0)
    max_width = max(width for _, _, width in widths)
    references = [
        (left, right)
        for left, right, width in widths
        if width >= max_width * 0.75
    ]
    if not references:
        references = [(left, right) for left, right, _ in widths]
    return (min(left for left, _ in references), max(right for _, right in references))


def _is_same_callout_cluster(previous: Region, current: Region) -> bool:
    prev_left, _, prev_right, prev_bottom = previous.bbox
    curr_left, curr_top, curr_right, _ = current.bbox
    if curr_top - prev_bottom > CALLOUT_MAX_VERTICAL_GAP:
        return False
    overlap_left = max(prev_left, curr_left)
    overlap_right = min(prev_right, curr_right)
    overlap = max(0.0, overlap_right - overlap_left)
    min_width = max(1.0, min(prev_right - prev_left, curr_right - curr_left))
    return (overlap / min_width) >= 0.55


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


def _normalize_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())



def _image_block_to_region(
    block: dict[str, Any],
    bbox: tuple[float, float, float, float],
    page_num: int,
    image_map: dict[int, dict[str, Any]],
) -> Region | None:
    width_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if width_area < 200:
        return None

    image_bytes: bytes | None = block.get("image")
    if image_bytes is None:
        image_bytes = image_map.get(block.get("xref"), {}).get("image")

    return Region(
        bbox=bbox,
        type="image",
        text="",
        image_bytes=image_bytes,
        confidence=0.9 if image_bytes else 0.3,
        page_num=page_num,
        metadata={"has_image_data": image_bytes is not None},
    )


def _fill_gaps_with_unknown(
    page: fitz.Page,
    regions: list[Region],
    page_num: int,
) -> None:
    page_rect = page.rect
    page_w = page_rect.width
    page_h = page_rect.height

    if not regions:
        regions.append(
            Region(
                bbox=(0, 0, page_w, page_h),
                type="unknown",
                text="",
                image_bytes=None,
                confidence=0.0,
                page_num=page_num,
            )
        )
        return

    # Bounding envelopes can cover real whitespace between separate columns.
    covered = [r.bbox for r in regions]

    _add_unknown_gaps(covered, page_w, page_h, regions, page_num)


def _merge_bboxes(
    bboxes: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    if not bboxes:
        return []
    sorted_b = sorted(bboxes, key=lambda b: (b[1], b[0]))
    merged = [list(sorted_b[0])]
    for b in sorted_b[1:]:
        if b[1] <= merged[-1][3] + 5:
            merged[-1][2] = max(merged[-1][2], b[2])
            merged[-1][3] = max(merged[-1][3], b[3])
        else:
            merged.append(list(b))
    return [tuple(b) for b in merged]


def _add_unknown_gaps(
    covered: list[tuple[float, float, float, float]],
    page_w: float,
    page_h: float,
    regions: list[Region],
    page_num: int,
) -> None:
    _shared_add_unknown_gaps(covered, page_w, page_h, regions, page_num)


def crop_region_to_image(
    page: fitz.Page, bbox: tuple[float, float, float, float], dpi: int = 200
) -> bytes:
    clip = fitz.Rect(bbox)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    return pix.tobytes("png")
