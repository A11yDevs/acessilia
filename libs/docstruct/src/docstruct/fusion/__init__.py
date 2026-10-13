"""docstruct.fusion — fusão multi-provider de documentos.

Porta do Tree Differ v2 (PR #98, Dr.DocBench) como biblioteca pura.
API principal: ``merge_blocks`` + ``blocks_from_provider``.
"""
from docstruct.fusion.differ import merge_blocks
from docstruct.fusion.flood import flood_guard
from docstruct.fusion.noise import is_junk, quality
from docstruct.fusion.types import DiffBlock, ProviderBlocks
from docstruct.fusion.convert import block_to_diff
from docstruct.fusion.judge import (
    debias,
    decide_pair,
    p2_from_logprobs,
    should_judge,
)
from docstruct.fusion.line_numbers import extract_line_numbers, line_number_chain
from docstruct.fusion.page_select import (
    blocks,
    fuse,
    page_agreement,
    page_norm,
    ratio,
    select_by_agreement,
    swap_low_agreement_pages,
    swap_norm,
)
from docstruct.fusion.repetition import (
    collapse,
    guard_page,
    is_blank_page,
    max_run,
    strip_comment,
)
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
    "blocks",
    "chunk_verse",
    "collapse",
    "debias",
    "decide_pair",
    "extract_line_numbers",
    "flood_guard",
    "fuse",
    "guard_page",
    "is_blank_page",
    "is_junk",
    "is_page_number",
    "join_tail",
    "line_number_chain",
    "max_run",
    "merge_blocks",
    "page_agreement",
    "page_norm",
    "page_number_position",
    "p2_from_logprobs",
    "quality",
    "ratio",
    "record_like",
    "select_by_agreement",
    "should_judge",
    "split_box_rows",
    "strip_comment",
    "swap_low_agreement_pages",
    "swap_norm",
    "tail_start",
    "tailjoin3",
    "verse_blocks",
    "verse_lines",
]
