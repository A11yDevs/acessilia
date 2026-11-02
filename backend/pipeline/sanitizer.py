"""Text sanitization.

Core migrated to docstruct.text.sanitize; re-exported here for
compatibility with existing imports.
"""
from __future__ import annotations

from docstruct.text.sanitize import (  # noqa: F401
    MARKDOWN_ARTIFACT_PATTERNS,
    PROMPT_LEAK_PATTERNS,
    contains_markdown_artifacts,
    contains_prompt_leak,
    sanitize_block_text,
    sanitize_text,
)

__all__ = [
    "MARKDOWN_ARTIFACT_PATTERNS",
    "PROMPT_LEAK_PATTERNS",
    "contains_markdown_artifacts",
    "contains_prompt_leak",
    "sanitize_block_text",
    "sanitize_text",
]
