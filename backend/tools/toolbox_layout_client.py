"""Cliente especializado para a capacidade document.layout.analyze da Toolbox.

Extrai e classifica regiões de layout (texto, imagem, tabela, fórmula, código,
etc.) de documentos, retornando dados estruturados por página.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxCapabilityClient

CAPABILITY = "document.layout.analyze"


class ToolboxLayoutClient(ToolboxCapabilityClient):
    """Cliente para extração de layout via Acessilia Toolbox.

    Encapsula a capacidade document.layout.analyze, que classifica regiões
    visuais das páginas em categorias semânticas (text_clean, table, formula,
    embedded_image, code_block, list_block, callout_box, etc.).
    """

    provider_key = "toolbox_layout_provider"

    async def analyze(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/document.layout.analyze:execute.

        Aceita upload direto (file_path) ou referência a artifact já armazenado
        (artifact_id). Retorna o JSON completo com regiões classificadas.

        Args:
            file_path: Caminho para o documento PDF/imagem.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            language: Idioma para análise (default: pt-BR).
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com a resposta da Toolbox contendo:
            - status: "succeeded"
            - capability: "document.layout.analyze"
            - provider: "docling-layout"
            - document: {page_count, region_count, pages: [{page_number, width, height, regions}]}
            - provenance: metadados de execução
        """
        result = await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            no_cache=use_remote_cache is False,
        )
        logger.info(
            "Toolbox: layout analisado ({} páginas, {} regiões, {} ms)",
            result.get("document", {}).get("page_count", "?"),
            result.get("document", {}).get("region_count", "?"),
            result.get("provenance", {}).get("duration_ms", "?"),
        )
        return result

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
