"""Parse plain text into canonical typed blocks.

Core migrated to docstruct.blocks.parser; re-exported here for
compatibility with existing imports. The backend passes a uuid-based
``id_factory`` to preserve the historical id scheme.
"""
from __future__ import annotations

from uuid import uuid4

from docstruct.blocks.parser import (  # noqa: F401
    _LATEX_COMMANDS,
    _looks_like_math_line,
    _looks_like_table_row,
    _parse_table_rows,
    _try_parse_marker_block,
    parse_text_to_blocks,
)


def _backend_id_factory(index: int) -> str:
    return f"blk-{uuid4().hex[:10]}-{index}"


def parse_text_to_blocks_backend(text: str) -> list[dict]:
    """Parse with the historical uuid id scheme."""
    return parse_text_to_blocks(text, id_factory=_backend_id_factory)


__all__ = [
    "parse_text_to_blocks",
    "parse_text_to_blocks_backend",
]
