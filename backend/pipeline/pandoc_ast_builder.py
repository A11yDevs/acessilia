"""Pandoc AST builder.

Core migrated to docstruct.export.pandoc_ast; re-exported here for
compatibility with existing imports.
"""
from __future__ import annotations

from docstruct.export.pandoc_ast import (  # noqa: F401
    build_pandoc_ast,
)
from docstruct.export.pandoc_ast import *  # noqa: F401,F403

__all__ = ["build_pandoc_ast"]
