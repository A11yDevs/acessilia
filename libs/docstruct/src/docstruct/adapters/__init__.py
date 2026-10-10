"""Provider format adapters for docstruct."""
from __future__ import annotations

from docstruct.adapters.mineru import (
    clean_mineru_text,
    extract_mineru_blocks,
    format_mineru_block_text,
)

__all__ = [
    "clean_mineru_text",
    "extract_mineru_blocks",
    "format_mineru_block_text",
]
