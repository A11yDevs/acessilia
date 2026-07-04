"""Exporters public API.

We expose thin wrappers around the existing core.exporters implementations
so that the rest of the codebase can depend on this ``adapters`` layer
instead of importing ``core.exporters`` directly.
"""

from pathlib import Path
from typing import Mapping, Any

# Import the legacy implementation functions
from core.exporters.txt_exporter import export_txt as _export_txt
from core.exporters.docx_exporter import export_docx as _export_docx
from core.exporters.pdf_exporter import export_pdf as _export_pdf
from core.exporters.audio_exporter import export_mp3 as _export_mp3

# Simple functional wrappers that keep the same signature used by the web UI
def export_txt(canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
    return _export_txt(canonical_doc, output_path, source_name)

def export_docx(canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
    return _export_docx(canonical_doc, output_path, source_name)

def export_pdf(canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
    return _export_pdf(canonical_doc, output_path, source_name)

def export_mp3(text_content: str, output_path: Path) -> Path:
    return _export_mp3(text_content, output_path)

# Factory helper – useful for the UI when the format is dynamic
_EXPORTER_MAP = {
    "txt": export_txt,
    "docx": export_docx,
    "pdf": export_pdf,
    "mp3": export_mp3,
}


def get_exporter(fmt: str):
    """Return the export function matching ``fmt`` (e.g., ``"pdf"``).

    Raises ``KeyError`` if the format is unknown.
    """
    return _EXPORTER_MAP[fmt]
