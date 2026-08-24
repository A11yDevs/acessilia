"""Ferramentas auxiliares de processamento de texto."""
from backend.tools.code_tools import normalize_code_text
from backend.tools.region_extractor import Region

# Sentinela devolvido pelo VisionAgent quando a imagem é uma fórmula matemática
FORMULA_SENTINEL = "[FORMULA]"

REGION_MARKERS = {
    "code_block": ("Início de código-fonte:", "Fim de código-fonte"),
    "list_block": ("Início de lista:", "Fim de lista"),
    "callout_box": ("Início de box:", "Fim de box"),
    "embedded_image": ("Início de imagem:", "Fim de imagem"),
}

CALLOUT_LABEL_MAP = {
    "note": "nota", "quote": "citação", "sidebar": "barra lateral",
    "warning": "aviso", "tip": "dica", "important": "importante",
    "admonition": "aviso", "caution": "aviso",
}

def apply_marker(text: str, classification: str, region: Region) -> str:
    markers = REGION_MARKERS.get(classification)
    if not markers: return text
    if classification == "code_block":
        text = normalize_code_text(text)
    start, end = markers
    lab = region.metadata.get("docling_label_kind") or region.metadata.get("docling_label", "")
    lab = str(lab).strip().lower().removeprefix("docitemlabel.").removeprefix("grouplabel.")
    custom = CALLOUT_LABEL_MAP.get(lab)
    if custom:
        start = f"Início de {custom}:"
        end = f"Fim de {custom}"
    return f"{start}\n{text}\n{end}"

def content_fingerprint(text: str) -> int:
    return hash(" ".join(text.lower().split()))

def overlaps_clean(bbox, clean_bboxes, threshold=0.3) -> bool:
    x0, y0, x1, y1 = bbox
    area = max((x1 - x0) * (y1 - y0), 1)
    for cb in clean_bboxes:
        ox0, oy0, ox1, oy1 = max(x0, cb[0]), max(y0, cb[1]), min(x1, cb[2]), min(y1, cb[3])
        if ox0 < ox1 and oy0 < oy1:
            if ((ox1 - ox0) * (oy1 - oy0)) / area >= threshold: return True
    return False
