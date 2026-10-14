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

import httpx

from backend.config.settings import settings
from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxClient,
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    _media_type,
    _raise_for_error,
)

CAPABILITY = "media.inspect"
EXECUTE_PATH = f"/v1/capabilities/{CAPABILITY}:execute"


class ToolboxMediaInspectClient(ToolboxClient):
    """Cliente para inspeção determinística de mídia via Acessilia Toolbox.

    Encapsula a capacidade media.inspect, que classifica a natureza do artefato
    (standalone_image / scanned_page / paginated_document / unknown) e emite o
    sinal requires_visual_inspection.
    """

    def __init__(
        self,
        base_url: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            provider=provider or settings.toolbox_media_inspect_provider,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

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
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        use_cache = (
            use_remote_cache
            if use_remote_cache is not None
            else settings.toolbox_use_remote_cache
        )
        url = f"{self.base_url}{EXECUTE_PATH}"

        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "provider": self.provider,
                }
                if not use_cache:
                    data["no_cache"] = True
                response = await self._client.post(url, data=data)
            else:
                with open(file_path, "rb") as f:
                    files = {
                        "file": (
                            file_path.name,
                            f,
                            _media_type(file_path),
                        )
                    }
                    params: dict[str, Any] = {
                        "provider": self.provider,
                    }
                    if not use_cache:
                        params["no_cache"] = True
                    response = await self._client.post(
                        url, files=files, data=params
                    )

            _raise_for_error(response, CAPABILITY)
            try:
                result = response.json()
            except ValueError as e:
                raise ToolboxContractViolation(
                    "Resposta de media.inspect não contém JSON válido"
                ) from e

            if not isinstance(result, dict):
                raise ToolboxContractViolation(
                    "Resposta de media.inspect deve ser um objeto JSON"
                )

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Inspeção de mídia falhou na Toolbox: "
                    f"status={result.get('status')}"
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

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao inspecionar mídia via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e
