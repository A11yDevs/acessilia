"""Cliente especializado para a capacidade document.ocr da Toolbox.

Extrai texto reconhecido por OCR de documentos e imagens, retornando
itens com confiança, página e bounding boxes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxCapabilityClient

CAPABILITY = "document.ocr"


class ToolboxOcrClient(ToolboxCapabilityClient):
    """Cliente para extração OCR via Acessilia Toolbox.

    Encapsula a capacidade document.ocr, que extrai texto reconhecido
    de imagens e documentos digitalizados.
    """

    provider_setting = "toolbox_ocr_provider"

    async def ocr(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        force_ocr: bool = True,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/document.ocr:execute.

        Args:
            file_path: Caminho para o documento ou imagem.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            language: Idioma para OCR (default: pt-BR).
            force_ocr: Se True, força OCR mesmo em texto nativo.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com items (lista de {text, label, confidence, page, bbox}),
            item_count, full_text, language.
        """
        result = await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            parameters={"ocr_lang": language, "force_ocr": force_ocr},
            no_cache=use_remote_cache is False,
        )
        logger.info(
            "Toolbox: OCR concluído ({} itens, force_ocr={})",
            result.get("document", {}).get("item_count", "?"),
            force_ocr,
        )
        return result


__all__ = ["ToolboxOcrClient"]
