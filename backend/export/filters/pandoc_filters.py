"""Export profile filters.

Core migrated to docstruct.export.filters; re-exported here for
compatibility with existing imports.
"""
from __future__ import annotations

from docstruct.export.filters import (  # noqa: F401
    apply_output_profile_filter,
    strip_internal_audit_blocks,
)

__all__ = ["apply_output_profile_filter", "strip_internal_audit_blocks"]
