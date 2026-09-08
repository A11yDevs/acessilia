"""Plain-text (TXT) export wrapper around the shared pandoc export entry point."""

from pathlib import Path
from typing import Any

from backend.export.pandoc_exporter import MSG_DEFAULT_ACCESSIBLE_TITLE
from backend.export.pandoc_exporter import export_accessible_document
from backend.i18n import t
from backend.log_messages import LOG_TXT_EXPORTED
from backend.tools.logger import logger


def export_txt(
    text: str | dict[str, Any],
    output_path: Path,
    title: str | None = None,
) -> Path:
    """Export a canonical document (or raw markdown/text) to plain text.

    Args:
        text (str | dict): Raw markdown/text or a canonical document mapping to export.
        output_path (Path): Destination file path for the rendered .txt output.
        title (str | None): Document title override; when None the localized default title is used.

    Returns:
        Path: The output_path where the .txt file was written.
    """
    result = export_accessible_document(
        text,
        output_path,
        format_name="txt",
        title=title or t(MSG_DEFAULT_ACCESSIBLE_TITLE),
        profile_name="txt",
    )
    logger.debug(t(LOG_TXT_EXPORTED).format(output_path=output_path))
    return result
