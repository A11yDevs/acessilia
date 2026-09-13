"""Cliente especializado para a capacidade document.ocr da Toolbox.

Extrai texto reconhecido por OCR de documentos e imagens, retornando
itens com confiança, página e bounding boxes.
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

CAPABILITY = "document.ocr"
EXECUTE_PATH = f"/v1/capabilities/{CAPABILITY}:execute"


class ToolboxOcrClient:
    """Cliente para extração OCR via Acessilia Toolbox.

    Encapsula a capacidade document.ocr, que extrai texto reconhecido
    de imagens e documentos digitalizados.
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

        Extrai texto por OCR de documentos/imagens.

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
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{EXECUTE_PATH}"

        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "language": language,
                    "force_ocr": force_ocr,
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
                        "language": language,
                        "force_ocr": force_ocr,
                        "provider": self.provider,
                    }
                    if use_remote_cache is False:
                        params["no_cache"] = True
                    response = await self._client.post(
                        url, files=files, data=params
                    )

            _raise_for_error(response, CAPABILITY)
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"OCR falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: OCR concluído ({} itens, force_ocr={})",
                result.get("document", {}).get("item_count", "?"),
                force_ocr,
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao executar OCR via Toolbox: {e}"
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


__all__ = ["ToolboxOcrClient"]