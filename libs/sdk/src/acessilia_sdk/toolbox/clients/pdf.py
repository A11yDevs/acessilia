"""Client for ``pdf.split`` and ``pdf.render``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

SPLIT_CAPABILITY = "pdf.split"
RENDER_CAPABILITY = "pdf.render"


class ToolboxPdfClient(ToolboxCapabilityClient):
    """Split a PDF into pages and render a page as PNG."""

    provider_key = "toolbox_pdf_provider"

    async def split(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/pdf.split:execute``.

        Returns the response envelope; its ``document`` holds ``page_count``,
        ``pages`` (per-page metadata) and ``source_filename``.
        """
        return await self._execute(
            SPLIT_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            no_cache=use_remote_cache is False,
        )

    async def render(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        page_number: int = 1,
        dpi: int = 150,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/pdf.render:execute``; ``page_number`` is 1-based.

        Returns the response envelope; its ``document`` holds ``page_number``,
        ``width``, ``height``, ``image_bytes_base64``, ``size_bytes`` and
        ``source_filename``.
        """
        return await self._execute(
            RENDER_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={"page_number": page_number, "dpi": dpi},
            no_cache=use_remote_cache is False,
        )


__all__ = ["RENDER_CAPABILITY", "SPLIT_CAPABILITY", "ToolboxPdfClient"]
