"""Client for ``document.export.docx``: a Pandoc AST rendered as DOCX.

The Toolbox renders the DOCX with its pinned Pandoc, sandboxed; see
:mod:`acessilia_sdk.toolbox.clients.pandoc_export` for how the file comes back.
Its ``document`` follows ``artifact/docx-export@1``.
"""

from __future__ import annotations

from acessilia_sdk.toolbox.clients.pandoc_export import PandocExportClient

CAPABILITY = "document.export.docx"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ToolboxDocxClient(PandocExportClient):
    """DOCX export."""

    provider_key = "toolbox_docx_provider"
    capability = CAPABILITY
    media_type = DOCX_MEDIA_TYPE
    format_name = "DOCX"
    # A DOCX file is a ZIP archive.
    magic = b"PK\x03\x04"


__all__ = ["CAPABILITY", "DOCX_MEDIA_TYPE", "ToolboxDocxClient"]
