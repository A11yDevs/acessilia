from pathlib import Path
from typing import Any

from bot.utils.logger import logger
from exporters.pandoc_exporter import export_accessible_document


def export_pdf(
    text: str | dict[str, Any],
    output_path: Path,
    title: str = "Documento acessível",
) -> Path:
    result = export_accessible_document(
        text,
        output_path,
        format_name="pdf",
        title=title,
        profile_name="pdf",
    )
    logger.debug("PDF exportado com bookmarks e numeracao: {}", output_path)
    return result
