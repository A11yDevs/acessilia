"""Structural validation for canonical documents, export profiles and output text.

Core migrated to docstruct.validation (pure, returns structured findings);
this bridge resolves findings through the backend i18n catalog, keeping the
localized-string contract for existing consumers. The docstruct msgids remain
here only as deprecated compatibility re-exports: import them from
``docstruct.validation`` instead.
"""
from __future__ import annotations

import warnings
from typing import Any

import docstruct.validation as _docstruct_validation
from acessilia_core.i18n import t

_DEPRECATED_MSGIDS = tuple(
    sorted(name for name in vars(_docstruct_validation) if name.startswith("MSG_"))
)
_DEPRECATED: dict[str, str] = {
    name: getattr(_docstruct_validation, name) for name in _DEPRECATED_MSGIDS
}

__all__ = [
    "validate_canonical_document",
    "validate_export_profile",
    "validate_output_text",
    "audit_canonical_document",
    *_DEPRECATED_MSGIDS,
]


def __getattr__(name: str) -> Any:
    if name in _DEPRECATED:
        warnings.warn(
            f"acessilia_core.pipeline.validators.{name} is deprecated; "
            "import it from docstruct.validation",
            DeprecationWarning,
            stacklevel=2,
        )
        return _DEPRECATED[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _resolve(findings: list) -> list[str]:
    return [t(msgid).format(**kwargs) for msgid, kwargs in findings]


def _resolve(findings: list) -> list[str]:
    return [t(msgid).format(**kwargs) for msgid, kwargs in findings]


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
