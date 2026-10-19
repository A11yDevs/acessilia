"""Client for ``document.layout.analyze``: classified visual regions per page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

CAPABILITY = "document.layout.analyze"


class ToolboxLayoutClient(ToolboxCapabilityClient):
    """Layout analysis: regions classified as text_clean, table, formula,
    embedded_image, code_block, list_block, callout_box, and so on."""

    provider_key = "toolbox_layout_provider"

    async def analyze(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/document.layout.analyze:execute``.

        Returns the response envelope; its ``document`` holds ``page_count``,
        ``region_count`` and ``pages`` ({page_number, width, height, regions}).
        """
        return await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            no_cache=use_remote_cache is False,
        )

    async def analyze_pages(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
    ) -> list[dict[str, Any]]:
        """Only the pages, each with ``page_number``, ``width``, ``height`` and
        ``regions`` (type, bbox, confidence, text, label)."""
        result = await self.analyze(
            file_path=file_path, artifact_id=artifact_id, language=language
        )
        pages = result.get("document", {}).get("pages", [])
        if isinstance(pages, dict):
            pages = list(pages.values())
        return pages

    async def analyze_page(
        self,
        page_number: int,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
    ) -> dict[str, Any] | None:
        """One page, or ``None`` when the document has no such page."""
        pages = await self.analyze_pages(
            file_path=file_path, artifact_id=artifact_id, language=language
        )
        for page in pages:
            if page.get("page_number") == page_number:
                return page
        return None


__all__ = ["CAPABILITY", "ToolboxLayoutClient"]
