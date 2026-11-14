"""Plain-text rendering.

Core migrated to docstruct.export.txt; this module keeps the file-write
contract for existing consumers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from docstruct.export.txt import (  # noqa: F401
    _render_block,
    _render_section,
    document_to_txt_lines,
)


def render_txt(
    document: dict[str, Any], output_path: Path, profile_name: str = "txt"
) -> Path:
    """Renders the canonical document into a plain-text file (see lib for the pure transform)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = document_to_txt_lines(document, profile=profile_name)
    output_path.write_text("\n".join(lines).strip(), encoding="utf-8")
    return output_path
