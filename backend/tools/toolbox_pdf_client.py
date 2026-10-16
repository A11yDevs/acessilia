"""Cliente especializado para capacidades PDF da Toolbox.

Encapsula pdf.split e pdf.render, que usam PyMuPDF in-process na Toolbox
para dividir PDFs em páginas individuais e renderizar páginas como PNG.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxCapabilityClient

SPLIT_CAPABILITY = "pdf.split"
RENDER_CAPABILITY = "pdf.render"


class ToolboxPdfClient(ToolboxCapabilityClient):
    """Cliente para operações PDF via Acessilia Toolbox.

    Encapsula as capacidades pdf.split (dividir PDF em páginas) e
    pdf.render (renderizar página como PNG).
    """

    provider_setting = "toolbox_pdf_provider"

    async def split(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/pdf.split:execute.

        Args:
            file_path: Caminho para o documento PDF.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com page_count, pages (lista de metadados por página),
            e source_filename.
        """
        result = await self._execute(
            SPLIT_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            no_cache=use_remote_cache is False,
        )
        logger.info(
            "Toolbox: PDF dividido ({} páginas)",
            result.get("document", {}).get("page_count", "?"),
        )
        return result

    async def render(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        page_number: int = 1,
        dpi: int = 150,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/pdf.render:execute.

        Args:
            file_path: Caminho para o documento PDF.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            page_number: Número da página a renderizar (1-based).
            dpi: Resolução da renderização (default: 150).
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com page_number, width, height, image_bytes_base64,
            size_bytes, source_filename.
        """
        result = await self._execute(
            RENDER_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={"page_number": page_number, "dpi": dpi},
            no_cache=use_remote_cache is False,
        )
        logger.info(
            "Toolbox: página {} renderizada ({}x{} px, {} dpi)",
            page_number,
            result.get("document", {}).get("width", "?"),
            result.get("document", {}).get("height", "?"),
            dpi,
        )
        return result


__all__ = ["ToolboxPdfClient"]
