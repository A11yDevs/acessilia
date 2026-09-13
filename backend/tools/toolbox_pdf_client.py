"""Cliente especializado para capacidades PDF da Toolbox.

Encapsula pdf.split e pdf.render, que usam PyMuPDF in-process na Toolbox
para dividir PDFs em páginas individuais e renderizar páginas como PNG.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import settings
from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    _media_type,
    _raise_for_error,
)

SPLIT_CAPABILITY = "pdf.split"
RENDER_CAPABILITY = "pdf.render"
SPLIT_PATH = f"/v1/capabilities/{SPLIT_CAPABILITY}:execute"
RENDER_PATH = f"/v1/capabilities/{RENDER_CAPABILITY}:execute"


class ToolboxPdfClient:
    """Cliente para operações PDF via Acessilia Toolbox.

    Encapsula as capacidades pdf.split (dividir PDF em páginas) e
    pdf.render (renderizar página como PNG).
    """

    def __init__(
        self,
        base_url: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.toolbox_base_url).rstrip("/")
        self.provider = provider or settings.toolbox_provider
        self.timeout_seconds = timeout_seconds or settings.toolbox_timeout_seconds
        self.api_key = api_key if api_key is not None else settings.toolbox_api_key
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds),
            headers=headers,
        )

    async def split(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/pdf.split:execute.

        Divide um PDF multi-página em páginas individuais.

        Args:
            file_path: Caminho para o documento PDF.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com page_count, pages (lista de metadados por página),
            e source_filename.
        """
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{SPLIT_PATH}"

        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "provider": self.provider,
                }
                if use_remote_cache is False:
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
                    if use_remote_cache is False:
                        params["no_cache"] = True
                    response = await self._client.post(
                        url, files=files, data=params
                    )

            _raise_for_error(response, SPLIT_CAPABILITY)
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Divisão de PDF falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: PDF dividido ({} páginas)",
                result.get("document", {}).get("page_count", "?"),
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao dividir PDF via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

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

        Renderiza uma página de PDF como imagem PNG.

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
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{RENDER_PATH}"

        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "provider": self.provider,
                    "page_number": page_number,
                    "dpi": dpi,
                }
                if use_remote_cache is False:
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
                        "page_number": page_number,
                        "dpi": dpi,
                    }
                    if use_remote_cache is False:
                        params["no_cache"] = True
                    response = await self._client.post(
                        url, files=files, data=params
                    )

            _raise_for_error(response, RENDER_CAPABILITY)
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Renderização de PDF falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: página {} renderizada ({}x{} px, {} dpi)",
                page_number,
                result.get("document", {}).get("width", "?"),
                result.get("document", {}).get("height", "?"),
                dpi,
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao renderizar PDF via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def health(self) -> dict[str, Any]:
        """Verifica se a Toolbox está operacional."""
        try:
            response = await self._client.get("/v1/health")
            _raise_for_error(response, "health")
            return response.json()
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao verificar health da Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def close(self) -> None:
        """Libera a conexão HTTP."""
        await self._client.aclose()


__all__ = ["ToolboxPdfClient"]