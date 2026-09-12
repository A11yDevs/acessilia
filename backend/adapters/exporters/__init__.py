"""Exporters public API.

We expose thin wrappers around the existing core.exporters implementations
so that the rest of the codebase can depend on this ``adapters`` layer
instead of importing ``core.exporters`` directly.
"""

from pathlib import Path
from typing import Mapping, Any
from backend.i18n import t
from backend.log_messages import (
    LOG_EXPORT_TXT_START,
    LOG_EXPORT_DOCX_START,
    LOG_EXPORT_PDF_START,
    LOG_EXPORT_PDF_UA_START,
    LOG_EXPORT_MP3_START,
)
from backend.tools.logger import logger

# Import the legacy implementation functions
from backend.export.exporters.txt_exporter import export_txt as _export_txt
from backend.export.exporters.docx_exporter import export_docx as _export_docx
from backend.export.exporters.pdf_exporter import export_pdf as _export_pdf
from backend.export.exporters.pdf_exporter import export_pdf_ua as _export_pdf_ua
from backend.export.exporters.audio_exporter import export_mp3 as _export_mp3


# Simple functional wrappers that keep the same signature used by the web UI
def export_txt(canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
    """Export a canonical document to plain text (TXT).

    Args:
        canonical_doc (Mapping[str, Any]): The canonical document structure to export; no default (required).
        output_path (Path): Destination file path for the exported TXT; no default (required).
        source_name (str): Original source document name used for metadata; no default (required).

    Returns:
        Path: The written output path.
    """
    logger.debug(t(LOG_EXPORT_TXT_START).format(path=output_path))
    return _export_txt(canonical_doc, output_path, source_name)


def export_docx(canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
    """Export a canonical document to a DOCX file.

    Args:
        canonical_doc (Mapping[str, Any]): The canonical document structure to export; no default (required).
        output_path (Path): Destination file path for the exported DOCX; no default (required).
        source_name (str): Original source document name used for metadata; no default (required).

    Returns:
        Path: The written output path.
    """
    logger.debug(t(LOG_EXPORT_DOCX_START).format(path=output_path))
    return _export_docx(canonical_doc, output_path, source_name)


def export_pdf(canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
    """Export a canonical document to a PDF file.

    Args:
        canonical_doc (Mapping[str, Any]): The canonical document structure to export; no default (required).
        output_path (Path): Destination file path for the exported PDF; no default (required).
        source_name (str): Original source document name used for metadata; no default (required).

    Returns:
        Path: The written output path.
    """
    logger.debug(t(LOG_EXPORT_PDF_START).format(path=output_path))
    return _export_pdf(canonical_doc, output_path, source_name)


def export_pdf_ua(canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
    """Export a canonical document to a PDF/UA file (accessible tagged PDF).

    Args:
        canonical_doc (Mapping[str, Any]): The canonical document structure to export; no default (required).
        output_path (Path): Destination file path for the exported PDF/UA; no default (required).
        source_name (str): Original source document name used for metadata; no default (required).

    Returns:
        Path: The written output path.
    """
    logger.debug(t(LOG_EXPORT_PDF_UA_START).format(path=output_path))
    return _export_pdf_ua(canonical_doc, output_path, source_name)


async def export_mp3(text_content: str, output_path: Path, **kwargs) -> Path:
    """Export plain text to an MP3 audio file.

    Args:
        text_content (str): Plain text content to be converted to audio; no default (required).
        output_path (Path): Destination file path for the exported MP3; no default (required).
        **kwargs (dict): Additional keyword arguments forwarded to the MP3 exporter (default: {}).

    Returns:
        Path: The written output path.
    """
    logger.debug(t(LOG_EXPORT_MP3_START).format(path=output_path))
    return await _export_mp3(text_content, output_path)


# Factory helper – useful for the UI when the format is dynamic
_EXPORTER_MAP = {
    "txt": export_txt,
    "docx": export_docx,
    "pdf": export_pdf,
    "pdf_ua": export_pdf_ua,
    "mp3": export_mp3,
}


def get_exporter(fmt: str):
    """Return the export function matching ``fmt`` (e.g., ``"pdf"``).

    Args:
        fmt (str): Export format key (one of ``"txt"``, ``"docx"``, ``"pdf"``, ``"pdf_ua"``, ``"mp3"``); no default (required).

    Returns:
        callable: The bound export function for the requested format.

    Raises:
        KeyError: If the format key is not known in the exporter map.
    """
    return _EXPORTER_MAP[fmt]
