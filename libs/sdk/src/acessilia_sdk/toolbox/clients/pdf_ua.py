"""Client for ``document.export.pdf_ua``: a Pandoc AST rendered as PDF/UA.

The Toolbox renders the PDF with Pandoc and TeX Live pinned in its own image;
see :mod:`acessilia_sdk.toolbox.clients.pandoc_export` for how the file comes
back. Its ``document`` follows ``artifact/pdf-export@1``.
"""

from __future__ import annotations

from acessilia_sdk.toolbox.clients.pandoc_export import (
    PANDOC_AST_KEYS,
    PandocExportClient,
    pandoc_payload,
)

CAPABILITY = "document.export.pdf_ua"
PDF_MEDIA_TYPE = "application/pdf"


class ToolboxPdfUaClient(PandocExportClient):
    """PDF/UA export."""

    provider_key = "toolbox_pdf_ua_provider"
    timeout_key = "toolbox_pdf_ua_timeout_seconds"
    capability = CAPABILITY
    media_type = PDF_MEDIA_TYPE
    format_name = "PDF"
    magic = b"%PDF-"


__all__ = ["CAPABILITY", "PANDOC_AST_KEYS", "ToolboxPdfUaClient", "pandoc_payload"]
