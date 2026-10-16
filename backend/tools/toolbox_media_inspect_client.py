"""Cliente especializado para a capacidade media.inspect da Toolbox.

Inspeciona binários de documento/imagem de forma determinística (dimensões,
proporção, contagem de páginas, natureza do artefato e necessidade de inspeção
visual). Usado pelo orquestrador para detectar imagens raster isoladas que
exigem audiodescrição pelo VisionAgent, mesmo quando o extrator estrutural
(Docling) não gera blocos `picture`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.config.settings import settings
from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxCapabilityClient,
    ToolboxContractViolation,
)

CAPABILITY = "media.inspect"


class ToolboxMediaInspectClient(ToolboxCapabilityClient):
    """Cliente para inspeção determinística de mídia via Acessilia Toolbox.

    Encapsula a capacidade media.inspect, que classifica a natureza do artefato
    (standalone_image / scanned_page / paginated_document / unknown) e emite o
    sinal requires_visual_inspection.
    """

    provider_key = "toolbox_media_inspect_provider"

    async def inspect(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/media.inspect:execute.

        Aceita upload direto (file_path) ou referência a artifact já armazenado
        (artifact_id). Retorna o dicionário de inspeção (`document` da resposta),
        compatível com o schema artifact/media-inspection@1.

        Args:
            file_path: Caminho para o documento PDF/imagem.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com os campos de inspeção (media_type, is_image, is_pdf,
            page_count, dimensions, artifact_nature, requires_visual_inspection, ...).
        """
        use_cache = (
            use_remote_cache
            if use_remote_cache is not None
            else settings.toolbox_use_remote_cache
        )
        result = await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            no_cache=not use_cache,
        )

        document = result.get("document")
        if not isinstance(document, dict):
            raise ToolboxContractViolation(
                "Resposta de media.inspect sem campo 'document'"
            )

        provenance = result.get("provenance")
        duration_ms = (
            provenance.get("duration_ms", "?")
            if isinstance(provenance, dict)
            else "?"
        )
        logger.info(
            "Toolbox: media.inspect concluído (nature={}, visual={}, {} ms)",
            document.get("artifact_nature", "?"),
            document.get("requires_visual_inspection", "?"),
            duration_ms,
        )
        return document


__all__ = ["ToolboxMediaInspectClient"]
