"""Cliente especializado para a capacidade document.layout.analyze da Toolbox.

Extrai e classifica regiões de layout (texto, imagem, tabela, fórmula, código,
etc.) de documentos, retornando dados estruturados por página.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import settings
from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityError,
    ToolboxClient,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnsupportedMediaType,
    _media_type,
    _raise_for_error,
)

CAPABILITY = "document.layout.analyze"
EXECUTE_PATH = f"/v1/capabilities/{CAPABILITY}:execute"


class ToolboxLayoutClient:
    """Cliente para extração de layout via Acessilia Toolbox.

    Encapsula a capacidade document.layout.analyze, que classifica regiões
    visuais das páginas em categorias semânticas (text_clean, table, formula,
    embedded_image, code_block, list_block, callout_box, etc.).
    """

    def __init__(
        self,
        base_url: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.toolbox_base_url).rstrip("/")
        self.provider = provider or "docling-layout"
        self.timeout_seconds = timeout_seconds or settings.toolbox_timeout_seconds
        self.api_key = api_key if api_key is not None else settings.toolbox_api_key

    async def analyze(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
    ) -> dict[str, Any]:
        """POST /v1/capabilities/document.layout.analyze:execute.

        Aceita upload direto (file_path) ou referência a artifact já armazenado
        (artifact_id). Retorna o JSON completo com regiões classificadas.

        Args:
            file_path: Caminho para o documento PDF/imagem.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            language: Idioma para análise (default: pt-BR).

        Returns:
            Dict com a resposta da Toolbox contendo:
            - status: "succeeded"
            - capability: "document.layout.analyze"
            - provider: "docling-layout"
            - document: {page_count, region_count, pages: [{page_number, dimensions, regions}]}
            - provenance: metadados de execução
        """
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{EXECUTE_PATH}"

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds)
            ) as client:
                headers = self._auth_headers

                if artifact_id:
                    data: dict[str, Any] = {
                        "artifact_id": artifact_id,
                        "language": language,
                        "provider": self.provider,
                    }
                    response = await client.post(
                        url, data=data, headers=headers
                    )
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
                            "language": language,
                            "provider": self.provider,
                        }
                        response = await client.post(
                            url, files=files, data=params, headers=headers
                        )

            _raise_for_error(response, CAPABILITY)
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Análise de layout falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: layout analisado ({} páginas, {} regiões, {} ms)",
                result.get("document", {}).get("page_count", "?"),
                result.get("document", {}).get("region_count", "?"),
                result.get("provenance", {}).get("duration_ms", "?"),
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao analisar layout via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def analyze_pages(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
    ) -> list[dict[str, Any]]:
        """Conveniência: retorna apenas a lista de páginas com regiões.

        Cada página contém:
        - page_number: int
        - width: float
        - height: float
        - regions: list[dict] com type, bbox, confidence, text, label
        """
        result = await self.analyze(
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
        )
        document = result.get("document", {})
        pages = document.get("pages", [])

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
        """Conveniência: retorna apenas os dados de uma página específica."""
        pages = await self.analyze_pages(
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
        )
        for page in pages:
            if page.get("page_number") == page_number:
                return page
        return None

    async def health(self) -> dict[str, Any]:
        """Verifica se a Toolbox está operacional (usa cliente genérico)."""
        client = ToolboxClient(
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            api_key=self.api_key,
        )
        return await client.health()

    @property
    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}


__all__ = ["ToolboxLayoutClient"]