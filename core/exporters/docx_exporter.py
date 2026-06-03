from pathlib import Path
from typing import Any

from core.utils.logger import logger
from exporters.pandoc_exporter import export_accessible_document


def export_docx(
    text: str | dict[str, Any],
    output_path: Path,
    filename: str = "",
) -> Path:
    result = export_accessible_document(
        text,
        output_path,
        format_name="docx",
        title=filename or "Documento acessível",
        profile_name="docx",
        filename=filename,
    )
    logger.debug("DOCX exportado: {}", output_path)
    return result
