"""Structural validation for canonical documents, export profiles and output text.

Core migrated to docstruct.validation (pure, returns structured findings);
this bridge resolves findings through the backend i18n catalog, keeping the
localized-string contract for existing consumers.
"""
from __future__ import annotations

from typing import Any

from backend.i18n import t
from docstruct.validation import (  # noqa: F401
    MSG_CANONICAL_DOC_NOT_OBJECT,
    MSG_FIELD_MISSING,
    MSG_SECTIONS_NOT_LIST,
    MSG_DUPLICATE_ID,
    MSG_PROMPT_LEAK_IN_BLOCK,
    MSG_MARKDOWN_IN_BLOCK,
    MSG_INCONSISTENT_CODE_INDENT,
    MSG_MULTIPLE_H1,
    MSG_MISSING_FIRST_H1,
    MSG_HEADING_LEVELS_SKIPPED,
    MSG_INTERNAL_LINK_BROKEN,
    MSG_UNKNOWN_EXPORT_PROFILE,
    MSG_BLOCK_NOT_ALLOWED_IN_PROFILE,
    MSG_PROMPT_LEAK_IN_OUTPUT,
    MSG_MARKDOWN_IN_OUTPUT,
    MSG_TECHNICAL_METADATA_IN_TXT,
    MSG_IMAGE_MISSING_ALT,
    MSG_TABLE_MISSING_HEADER,
    MSG_TABLE_LEGACY_FALLBACK,
    MSG_DOCUMENT_NO_SECTIONS,
    MSG_NO_ID_PLACEHOLDER,
    MSG_TABLE_EMPTY,
    MSG_TABLE_ROWS_INVALID,
    MSG_TABLE_ROW_INVALID,
    MSG_TABLE_COLUMNS_INCONSISTENT,
    MSG_TABLE_CELL_NOT_TEXT,
    MSG_TABLE_CELL_EMPTY,
    MSG_TABLE_AST_INVALID,
    MSG_TABLE_AST_NO_BODY,
    MSG_TABLE_AST_SECTION_INVALID,
    MSG_TABLE_AST_ROW_INVALID,
    MSG_TABLE_AST_ROW_NO_CELLS,
    MSG_TABLE_AST_CELL_INVALID,
    MSG_TABLE_AST_CELL_NO_TEXT,
    MSG_TABLE_AST_WIDTH_INCONSISTENT,
    Finding,
    audit_canonical_document as _lib_audit,
    validate_canonical_document as _lib_validate_doc,
    validate_export_profile as _lib_validate_profile,
    validate_output_text as _lib_validate_output,
)

__all__ = [
    "validate_canonical_document",
    "validate_export_profile",
    "validate_output_text",
    "audit_canonical_document",
] + [n for n in dir() if n.startswith("MSG_")]


def _resolve(findings: list) -> list[str]:
    return [t(msgid).format(**kwargs) for msgid, kwargs in findings]


def validate_canonical_document(document: dict[str, Any]) -> list[str]:
    """Validate a canonical document structure; returns localized error messages."""
    return _resolve(_lib_validate_doc(document))


def validate_export_profile(
    profile_name: str,
    document: dict[str, Any],
) -> list[str]:
    """Check block verbosity against the named export profile; localized messages."""
    return _resolve(_lib_validate_profile(profile_name, document))


def validate_output_text(text: str, profile_name: str) -> list[str]:
    """Scan the final exported text for forbidden artifacts; localized messages."""
    return _resolve(_lib_validate_output(text, profile_name))


def audit_canonical_document(document: dict[str, Any]) -> dict[str, list[str]]:
    """Detailed structural audit (BLOCKER/WARNING); localized messages."""
    report = _lib_audit(document)
    return {
        severity: _resolve(findings)
        for severity, findings in report.items()
    }
