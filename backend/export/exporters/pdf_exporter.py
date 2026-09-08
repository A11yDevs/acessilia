"""PDF and PDF/UA export wrappers around the shared pandoc export entry point."""

from pathlib import Path
from typing import Any

from backend.export.pandoc_exporter import MSG_DEFAULT_ACCESSIBLE_TITLE
from backend.export.pandoc_exporter import export_accessible_document
from backend.i18n import t
from backend.log_messages import LOG_PDF_EXPORTED, LOG_PDF_UA_EXPORTED
from backend.tools.logger import logger


def export_pdf(
    text: str | dict[str, Any],
    output_path: Path,
    title: str | None = None,
) -> Path:
    """Export a canonical document (or raw markdown/text) to a marked accessible PDF.

    Args:
        text (str | dict): Raw markdown/text or a canonical document mapping to export.
        output_path (Path): Destination file path for the rendered PDF.
        title (str | None): Document title override; when None the localized default title is used.

    Returns:
        Path: The output_path where the PDF was written.
    """
    result = export_accessible_document(
        text,
        output_path,
        format_name="pdf",
        title=title or t(MSG_DEFAULT_ACCESSIBLE_TITLE),
        profile_name="pdf",
    )
    logger.debug(
        t(LOG_PDF_EXPORTED).format(output_path=output_path)
    )
    return result


def export_pdf_ua(
    text: str | dict[str, Any],
    output_path: Path,
    title: str | None = None,
) -> Path:
    """Export a canonical document (or raw markdown/text) to an accessible PDF/UA document.

    Args:
        text (str | dict): Raw markdown/text or a canonical document mapping to export.
        output_path (Path): Destination file path for the rendered PDF/UA.
        title (str | None): Document title override; when None the localized default title is used.

    Returns:
        Path: The output_path where the PDF/UA was written.
    """
    result = export_accessible_document(
        text,
        output_path,
        format_name="pdf_ua",
        title=title or t(MSG_DEFAULT_ACCESSIBLE_TITLE),
        profile_name="pdf_ua",
    )
    logger.debug(t(LOG_PDF_UA_EXPORTED).format(output_path=output_path))
    return result
