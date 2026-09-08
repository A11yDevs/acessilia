"""DOCX export wrapper around the shared pandoc export entry point."""

from pathlib import Path
from typing import Any

from backend.export.pandoc_exporter import MSG_DEFAULT_ACCESSIBLE_TITLE
from backend.export.pandoc_exporter import export_accessible_document
from backend.i18n import t
from backend.log_messages import LOG_DOCX_EXPORTED
from backend.tools.logger import logger


def export_docx(
    text: str | dict[str, Any],
    output_path: Path,
    filename: str = "",
) -> Path:
    """Export a canonical document (or raw markdown/text) to a Word .docx file.

    Args:
        text (str | dict): Raw markdown/text or a canonical document mapping to export.
        output_path (Path): Destination file path for the rendered .docx output.
        filename (str): Optional document title/filename hint; when empty the localized default title is used (default "").

    Returns:
        Path: The output_path where the .docx file was written.
    """
    result = export_accessible_document(
        text,
        output_path,
        format_name="docx",
        title=filename or t(MSG_DEFAULT_ACCESSIBLE_TITLE),
        profile_name="docx",
        filename=filename,
    )
    logger.debug(t(LOG_DOCX_EXPORTED).format(output_path=output_path))
    return result
