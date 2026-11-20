"""PDF/UA export wrapper around the shared pandoc export entry point."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from acessilia_core.config import ExportConfig, ToolboxConfig
from acessilia_core.export.messages import MSG_DEFAULT_ACCESSIBLE_TITLE
from acessilia_core.export.pandoc_exporter import export_accessible_document
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import LOG_PDF_UA_EXPORTED
from acessilia_core.logger import logger


def export_pdf_ua(
    text: str | dict[str, Any],
    output_path: Path,
    title: str | None = None,
    *,
    export: ExportConfig,
    toolbox: ToolboxConfig,
    check_cancelled: Callable[[], None] | None = None,
) -> Path:
    """Export a canonical document (or raw markdown/text) to an accessible PDF/UA document.

    Args:
        text (str | dict): Raw markdown/text or a canonical document mapping to export.
        output_path (Path): Destination file path for the rendered PDF/UA.
        title (str | None): Document title override; when None the localized default title is used.
        export (ExportConfig): The run's export configuration, which enables the Toolbox rendering.
        toolbox (ToolboxConfig): The run's Toolbox configuration, which renders it.
        check_cancelled (Callable[[], None] | None): Optional cancellation probe checked before
            each PDF/UA math-isolation retry render.

    Returns:
        Path: The output_path where the PDF/UA was written.
    """
    result = export_accessible_document(
        text,
        output_path,
        format_name="pdf_ua",
        title=title or t(MSG_DEFAULT_ACCESSIBLE_TITLE),
        profile_name="pdf_ua",
        export=export,
        toolbox=toolbox,
        check_cancelled=check_cancelled,
    )
    logger.debug(t(LOG_PDF_UA_EXPORTED).format(output_path=output_path))
    return result
