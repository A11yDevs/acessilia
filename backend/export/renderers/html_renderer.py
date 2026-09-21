"""Standalone HTML rendering.

Core migrated to docstruct.export.html; this module resolves the i18n
labels and keeps the file-write contract.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.export.pandoc_exporter import MSG_DEFAULT_ACCESSIBLE_TITLE
from backend.i18n import t
from docstruct.export.html import (  # noqa: F401
    HtmlLabels,
    _collect_section,
    _all_blocks,
    _render_block,
    _render_html_table_row,
    document_to_html,
)

# Canonical msgids (kept here: consumed by scripts/gen_locale_catalogs)
MSG_HTML_TABLE_OF_CONTENTS = "Contents"
MSG_HTML_TECHNICAL_METADATA = "Technical metadata"
MSG_HTML_IMAGE_DESCRIPTION = "Image description"


def render_html(
    document: dict[str, Any], output_path: Path, profile_name: str = "html"
) -> Path:
    """Renders the canonical document into a standalone HTML page (labels via i18n)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    labels = HtmlLabels(
        default_title=document.get("title") or t(MSG_DEFAULT_ACCESSIBLE_TITLE),
        table_of_contents=t(MSG_HTML_TABLE_OF_CONTENTS),
        technical_metadata=t(MSG_HTML_TECHNICAL_METADATA),
        image_description=t(MSG_HTML_IMAGE_DESCRIPTION),
    )
    html = document_to_html(document, profile=profile_name, labels=labels)
    output_path.write_text(html, encoding="utf-8")
    return output_path
