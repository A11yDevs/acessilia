"""Structural validation for canonical documents, export profiles and output text.

Core migrated to docstruct.validation (pure, returns structured findings);
this bridge resolves findings through the backend i18n catalog, keeping the
localized-string contract for existing consumers. The docstruct msgids remain
here only as deprecated compatibility re-exports: import them from
``docstruct.validation`` instead.
"""
from __future__ import annotations

from typing import Any

import docstruct.validation as _docstruct_validation
from acessilia_core.i18n import t
from acessilia_core.pipeline._deprecations import _deprecated_attribute
from acessilia_sdk.i18n.translation import resolve_findings

_DEPRECATED_MSGIDS = (
    "MSG_BLOCK_NOT_ALLOWED_IN_PROFILE",
    "MSG_CANONICAL_DOC_NOT_OBJECT",
    "MSG_DOCUMENT_NO_SECTIONS",
    "MSG_DUPLICATE_ID",
    "MSG_FIELD_MISSING",
    "MSG_HEADING_LEVELS_SKIPPED",
    "MSG_IMAGE_MISSING_ALT",
    "MSG_INCONSISTENT_CODE_INDENT",
    "MSG_INTERNAL_LINK_BROKEN",
    "MSG_MARKDOWN_IN_BLOCK",
    "MSG_MARKDOWN_IN_OUTPUT",
    "MSG_MISSING_FIRST_H1",
    "MSG_MULTIPLE_H1",
    "MSG_NO_ID_PLACEHOLDER",
    "MSG_PROMPT_LEAK_IN_BLOCK",
    "MSG_PROMPT_LEAK_IN_OUTPUT",
    "MSG_SECTIONS_NOT_LIST",
    "MSG_TABLE_AST_CELL_INVALID",
    "MSG_TABLE_AST_CELL_NO_TEXT",
    "MSG_TABLE_AST_INVALID",
    "MSG_TABLE_AST_NO_BODY",
    "MSG_TABLE_AST_ROW_INVALID",
    "MSG_TABLE_AST_ROW_NO_CELLS",
    "MSG_TABLE_AST_SECTION_INVALID",
    "MSG_TABLE_AST_WIDTH_INCONSISTENT",
    "MSG_TABLE_CELL_EMPTY",
    "MSG_TABLE_CELL_NOT_TEXT",
    "MSG_TABLE_COLUMNS_INCONSISTENT",
    "MSG_TABLE_EMPTY",
    "MSG_TABLE_LEGACY_FALLBACK",
    "MSG_TABLE_MISSING_HEADER",
    "MSG_TABLE_ROW_INVALID",
    "MSG_TABLE_ROWS_INVALID",
    "MSG_TECHNICAL_METADATA_IN_TXT",
    "MSG_UNKNOWN_EXPORT_PROFILE",
)
_DEPRECATED: dict[str, Any] = {
    name: getattr(_docstruct_validation, name)
    for name in (*_DEPRECATED_MSGIDS, "Finding")
}

__all__ = [
    "validate_canonical_document",
    "validate_export_profile",
    "validate_output_text",
    "audit_canonical_document",
    *_DEPRECATED_MSGIDS,
]


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_DEPRECATED))


def __getattr__(name: str) -> Any:
    return _deprecated_attribute(__name__, name, "docstruct.validation", _DEPRECATED)


def _resolve(findings: list) -> list[str]:
    return resolve_findings(findings, t)


def validate_canonical_document(document: dict[str, Any]) -> list[str]:
    """Validate a canonical document structure; returns localized error messages."""
    return _resolve(_docstruct_validation.validate_canonical_document(document))


def validate_export_profile(
    profile_name: str,
    document: dict[str, Any],
) -> list[str]:
    """Check block verbosity against the named export profile; localized messages."""
    return _resolve(
        _docstruct_validation.validate_export_profile(profile_name, document)
    )


def validate_output_text(text: str, profile_name: str) -> list[str]:
    """Scan the final exported text for forbidden artifacts; localized messages."""
    return _resolve(_docstruct_validation.validate_output_text(text, profile_name))


def audit_canonical_document(document: dict[str, Any]) -> dict[str, list[str]]:
    """Detailed structural audit (BLOCKER/WARNING); localized messages."""
    report = _docstruct_validation.audit_canonical_document(document)
    return {
        severity: _resolve(findings)
        for severity, findings in report.items()
    }
