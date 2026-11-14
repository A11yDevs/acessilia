"""Canonical English msgids of the export: the default title and the export errors.

Callers resolve them with :func:`backend.i18n.t` when they run, so the request
locale applies. They live apart from ``pandoc_exporter`` so that the renderers
and exporters can use the default title without importing the module that
imports them, which was an import cycle (``pandoc_exporter`` ↔
``renderers/html_renderer``).
"""

from __future__ import annotations

#: Canonical English msgid for a default document title used when the caller passes none.
MSG_DEFAULT_ACCESSIBLE_TITLE: str = "Accessible document"
#: Canonical English msgid for a docx export requested while TOOLBOX_DOCX_ENABLED is false.
MSG_DOCX_DISABLED: str = "DOCX export is disabled (TOOLBOX_DOCX_ENABLED=false)"
#: Canonical English msgid for a pdf_ua export requested while TOOLBOX_PDF_UA_ENABLED is false.
MSG_PDF_UA_DISABLED: str = "PDF/UA export is disabled (TOOLBOX_PDF_UA_ENABLED=false)"
#: Canonical English msgid template for an audit failure; {findings} is substituted by callers after lookup.
MSG_AUDIT_FAILED: str = "Audit failed: {findings}"
#: Canonical English msgid template for an unsupported export format; {format_name} is substituted by callers after lookup.
MSG_UNSUPPORTED_EXPORT_FORMAT: str = "Unsupported export format: {format_name}"


__all__ = [
    "MSG_AUDIT_FAILED",
    "MSG_DEFAULT_ACCESSIBLE_TITLE",
    "MSG_DOCX_DISABLED",
    "MSG_PDF_UA_DISABLED",
    "MSG_UNSUPPORTED_EXPORT_FORMAT",
]
