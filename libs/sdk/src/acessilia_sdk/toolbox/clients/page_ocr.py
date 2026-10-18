"""Client for ``document.ocr.page``: whole-page transcription by a VLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

CAPABILITY = "document.ocr.page"


class ToolboxPageOcrClient(ToolboxCapabilityClient):
    """Whole-page transcription (Qwen3-VL, dots.ocr, DeepSeek-OCR-2, TeleOCR)."""

    provider_key = "toolbox_page_ocr_provider"

    async def transcribe(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/document.ocr.page:execute``.

        Returns the response envelope; its ``document`` holds ``markdown``,
        ``finish`` (why generation stopped) and ``provider``.
        """
        return await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            parameters={"language": language},
            no_cache=use_remote_cache is False,
        )


__all__ = ["CAPABILITY", "ToolboxPageOcrClient"]
