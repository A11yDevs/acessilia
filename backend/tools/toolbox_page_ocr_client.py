"""Cliente especializado para a capacidade document.ocr.page da Toolbox.

Extrai a transcrição de página inteira por OCR de página (VLM), retornando o
markdown da página e o motivo de parada da geração. É a fonte B do híbrido de
página do Dr.DocBench (PR #125): quando Docling e MinerU discordam muito, a
página VLM substitui a saída do differ.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxCapabilityClient

CAPABILITY = "document.ocr.page"


class ToolboxPageOcrClient(ToolboxCapabilityClient):
    """Cliente para transcrição de página inteira via Acessilia Toolbox.

    Encapsula a capacidade document.ocr.page, que transcreve uma página
    completa com um modelo VLM (Qwen3-VL, dots.ocr, DeepSeek-OCR-2, TeleOCR).
    """

    provider_setting = "toolbox_page_ocr_provider"

    async def transcribe(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/document.ocr.page:execute.

        Args:
            file_path: Caminho para a imagem da página.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            language: Idioma do documento (default: pt-BR).
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com markdown, finish (motivo de parada da geração) e provider.
        """
        result = await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            parameters={"language": language},
            no_cache=use_remote_cache is False,
        )
        logger.info(
            "Toolbox: OCR de página concluído (provider={}, finish={})",
            self.provider,
            result.get("document", {}).get("finish", "?"),
        )
        return result


__all__ = ["ToolboxPageOcrClient"]
