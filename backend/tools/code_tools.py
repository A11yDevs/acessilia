"""Code text normalization tools.

Core migrated to docstruct.text.code_reflow; re-exported here for
compatibility with existing imports.
"""
from __future__ import annotations

from docstruct.text.code_reflow import normalize_code_text  # noqa: F401

__all__ = ["normalize_code_text"]
