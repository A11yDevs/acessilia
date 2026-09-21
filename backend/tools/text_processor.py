"""Paragraph re-fusion and simple markdown parsing.

Core migrated to docstruct.text.paragraphs; re-exported here for
compatibility with existing imports.
"""
from __future__ import annotations

from docstruct.text.paragraphs import (  # noqa: F401
    merge_broken_paragraphs,
    parse_markdown_and_descriptions,
)

__all__ = ["merge_broken_paragraphs", "parse_markdown_and_descriptions"]
