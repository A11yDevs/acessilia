"""Client for ``document.ocr``: recognized text from images and scanned documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

CAPABILITY = "document.ocr"


class ToolboxOcrClient(ToolboxCapabilityClient):
    """OCR through the Toolbox."""

    provider_key = "toolbox_ocr_provider"

    async def ocr(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        force_ocr: bool = True,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/document.ocr:execute``.

        ``force_ocr`` runs OCR even over native text. ``use_remote_cache=False``
        forces a fresh run on the Toolbox. Returns the response envelope; its
        ``document`` holds ``items`` ({text, label, confidence, page, bbox}),
        ``item_count``, ``full_text`` and ``language``.
        """
        return await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            parameters={"ocr_lang": language, "force_ocr": force_ocr},
            no_cache=use_remote_cache is False,
        )


__all__ = ["CAPABILITY", "ToolboxOcrClient"]
