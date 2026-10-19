"""Dr.DocBench markdown export — writes benchmark-format markdown directly.

Unlike the other exporters, this bypasses the pandoc pipeline entirely: the
benchmark requires raw markdown (HTML tables, LaTeX), not a rendered format.
"""

from pathlib import Path
from typing import Any

from docstruct.export.markdown import document_to_markdown

from backend.tools.logger import logger


def export_drbench_md(
    text: str | dict[str, Any],
    output_path: Path,
    title: str | None = None,
) -> Path:
    """Export canonical text/content to a ``*.drbench.md`` benchmark file.

    Args:
        text (str | dict): Raw markdown/text or a canonical document mapping.
        output_path (Path): Destination ``.drbench.md`` file path.
        title (str | None): Unused; kept for exporter signature compatibility.

    Returns:
        Path: The output_path where the .drbench.md file was written.
    """
    content = document_to_markdown(text) if isinstance(text, dict) else text

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logger.debug("Dr.DocBench markdown exported to {}", output_path)
    return output_path


__all__ = ["export_drbench_md"]
