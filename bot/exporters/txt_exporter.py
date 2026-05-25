from pathlib import Path
from typing import Any

from bot.utils.logger import logger
from exporters.pandoc_exporter import export_accessible_document


def export_txt(
    text: str | dict[str, Any],
    output_path: Path,
    title: str = "Documento acessível",
) -> Path:
    result = export_accessible_document(
        text,
        output_path,
        format_name="txt",
        title=title,
        profile_name="txt",
    )
    logger.debug("TXT exportado: {}", output_path)
    return result
