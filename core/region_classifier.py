from __future__ import annotations

from core.region_extractor import Region

TEXT_CLEAN_MIN_DENSITY = 0.015
TEXT_CLEAN_MIN_CHARS = 20
SCANNED_MAX_DENSITY = 0.005
IMAGE_CONFIDENCE_THRESHOLD = 0.5
UNKNOWN_MIN_AREA = 8000
UNKNOWN_MIN_DIM = 40

DOCLING_CLASSIFICATION = {
    "image": "embedded_image",
    "table": "table",
    "formula": "formula",
    "heading": "text_clean",
    "caption": "text_clean",
    "list": "list_block",
    "code": "code_block",
    "callout": "callout_box",
    "text": "text_clean",
}


def classify_region(region: Region) -> str:
    # Docling regions come with pre-classified type
    if region.metadata.get("source") == "docling":
        docling_type = region.type
        result = DOCLING_CLASSIFICATION.get(docling_type)
        if result:
            return result

    if region.type == "image":
        if region.image_bytes is not None and region.confidence >= IMAGE_CONFIDENCE_THRESHOLD:
            return "embedded_image"
        if _region_area(region) > UNKNOWN_MIN_AREA:
            return "unknown"
        return "ignore"

    if region.type == "table":
        if region.text.strip():
            return "table"
        if _region_area(region) > UNKNOWN_MIN_AREA:
            return "table"
        return "ignore"

    if region.type == "formula":
        if _region_area(region) > 500:
            return "formula"
        return "ignore"

    if region.type == "text":
        total_chars = region.metadata.get("total_chars", 0)
        text_density = region.metadata.get("text_density", 0)
        area = _region_area(region)
        subtype = region.metadata.get("subtype", "")

        if subtype == "code" and total_chars >= 10:
            return "code_block"
        if subtype == "list" and total_chars >= 10:
            line_count = region.metadata.get("line_count", 0)
            if line_count >= 2 or total_chars >= 50:
                return "list_block"

        if total_chars >= TEXT_CLEAN_MIN_CHARS and text_density >= TEXT_CLEAN_MIN_DENSITY:
            return "text_clean"

        if total_chars > 5 and text_density >= SCANNED_MAX_DENSITY:
            return "text_scanned"

        if area > UNKNOWN_MIN_AREA and not _is_too_thin_or_small(region):
            return "unknown"
        return "ignore"

    if region.type == "unknown":
        area = _region_area(region)
        if area > UNKNOWN_MIN_AREA and not _is_too_thin_or_small(region):
            return "unknown"
        return "ignore"

    return "ignore"


def region_needs_vision(classification: str) -> bool:
    return classification in ("text_scanned", "embedded_image", "unknown", "table", "formula")


def region_has_markers(classification: str) -> bool:
    return classification in ("code_block", "callout_box", "list_block", "embedded_image")


def region_prompt_key(classification: str) -> str:
    return {
        "embedded_image": "regiao_imagem",
        "text_scanned": "regiao_texto_escaneado",
        "unknown": "regiao_texto_escaneado",
        "table": "regiao_tabela",
        "formula": "regiao_formula",
    }.get(classification, "regiao_texto_escaneado")


def _region_area(region: Region) -> float:
    return (region.bbox[2] - region.bbox[0]) * (region.bbox[3] - region.bbox[1])


def _is_too_thin_or_small(region: Region) -> bool:
    w = region.bbox[2] - region.bbox[0]
    h = region.bbox[3] - region.bbox[1]
    if w < UNKNOWN_MIN_DIM or h < UNKNOWN_MIN_DIM:
        return True
    if w > 0 and h > 0 and (w / h > 15 or h / w > 15):
        return True
    return False
