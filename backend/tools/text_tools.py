"""Ferramentas auxiliares de processamento de texto."""
from backend.tools.code_tools import normalize_code_text
from backend.tools.region_extractor import Region

# Geometria/fingerprint migrados para a lib docstruct (Fase 2 do plano).
# Reexportados aqui para compatibilidade com imports existentes.
from docstruct.geometry import content_fingerprint, overlaps_clean  # noqa: F401

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

# content_fingerprint e overlaps_clean agora vivem em docstruct.geometry
# (reexportados no topo do arquivo).
