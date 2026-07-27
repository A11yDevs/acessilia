from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import fitz


@dataclass
class Region:
    bbox: tuple[float, float, float, float]
    type: str
    text: str
    image_bytes: bytes | None
    confidence: float
    page_num: int
    metadata: dict[str, Any] = field(default_factory=dict)


MONOSPACE_FONTS = {
    "courier",
    "consolas",
    "monaco",
    "menlo",
    "monospace",
    "dejavu sans mono",
    "liberation mono",
    "courier new",
    "lucida console",
    "source code pro",
    "fira code",
    "sf mono",
    "jetbrains mono",
    "cascadia code",
    "droid sans mono",
    "ubuntu mono",
    "inconsolata",
    "anonymous pro",
}

LIST_LINE_PATTERNS = (
    "- ",
    "* ",
    "+ ",
    "• ",
    "‣ ",
    "⁃ ",
    "o ",
    "§ ",
    "→ ",
    "⇒ ",
)


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

    covered = _merge_bboxes([r.bbox for r in regions])

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
    y_stops = sorted({0} | {c[3] for c in covered} | {page_h})
    for i in range(len(y_stops) - 1):
        y0 = y_stops[i]
        y1 = y_stops[i + 1]
        gap_height = y1 - y0
        if gap_height < 20:
            continue

        gap_x_stops = sorted(
            {0} | {c[2] for c in covered if c[1] < y1 and c[3] > y0} | {page_w}
        )
        for j in range(len(gap_x_stops) - 1):
            x0 = gap_x_stops[j]
            x1 = gap_x_stops[j + 1]
            gap_width = x1 - x0
            if gap_width < 30:
                continue

            gap_area = gap_width * gap_height
            if gap_area < 500:
                continue

            regions.append(
                Region(
                    bbox=(x0, y0, x1, y1),
                    type="unknown",
                    text="",
                    image_bytes=None,
                    confidence=0.0,
                    page_num=page_num,
                )
            )


def crop_region_to_image(
    page: fitz.Page, bbox: tuple[float, float, float, float], dpi: int = 200
) -> bytes:
    clip = fitz.Rect(bbox)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    return pix.tobytes("png")
