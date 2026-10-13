"""docstruct.fusion — fusão multi-provider de documentos.

Porta do Tree Differ v2 (PR #98, Dr.DocBench) como biblioteca pura.
API principal: ``merge_blocks`` + ``blocks_from_provider``.
"""
from docstruct.fusion.differ import merge_blocks
from docstruct.fusion.flood import flood_guard
from docstruct.fusion.noise import is_junk, quality
from docstruct.fusion.types import DiffBlock, ProviderBlocks
from docstruct.fusion.convert import block_to_diff
from docstruct.fusion.line_numbers import extract_line_numbers, line_number_chain
from docstruct.fusion.tailjoin import (
    is_page_number,
    join_tail,
    page_number_position,
    tail_start,
    tailjoin3,
)
from docstruct.fusion.verse import (
    chunk_verse,
    record_like,
    split_box_rows,
    verse_blocks,
    verse_lines,
)

__all__ = [
    "DiffBlock",
    "ProviderBlocks",
    "block_to_diff",
    "chunk_verse",
    "extract_line_numbers",
    "flood_guard",
    "is_junk",
    "is_page_number",
    "join_tail",
    "line_number_chain",
    "merge_blocks",
    "page_number_position",
    "quality",
    "record_like",
    "split_box_rows",
    "tail_start",
    "tailjoin3",
    "verse_blocks",
    "verse_lines",
]
