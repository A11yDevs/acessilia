"""docstruct.fusion — fusão multi-provider de documentos.

Porta do Tree Differ v2 (PR #98, Dr.DocBench) como biblioteca pura.
API principal: ``merge_blocks`` + ``blocks_from_provider``.
"""
from docstruct.fusion.differ import merge_blocks
from docstruct.fusion.noise import is_junk, quality
from docstruct.fusion.types import DiffBlock, ProviderBlocks
from docstruct.fusion.convert import block_to_diff

__all__ = [
    "DiffBlock",
    "ProviderBlocks",
    "block_to_diff",
    "is_junk",
    "merge_blocks",
    "quality",
]
