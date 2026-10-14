"""Cliente especializado para a capacidade document.ocr.page da Toolbox.

Extrai a transcrição de página inteira por OCR de página (VLM), retornando o
markdown da página e o motivo de parada da geração. É a fonte B do híbrido de
página do Dr.DocBench (PR #125): quando Docling e MinerU discordam muito, a
página VLM substitui a saída do differ.
"""

from __future__ import annotations

import json
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

CAPABILITY = "document.ocr.page"
EXECUTE_PATH = f"/v1/capabilities/{CAPABILITY}:execute"


class ToolboxPageOcrClient(ToolboxClient):
    """Cliente para transcrição de página inteira via Acessilia Toolbox.

    Encapsula a capacidade document.ocr.page, que transcreve uma página
    completa com um modelo VLM (Qwen3-VL, dots.ocr, DeepSeek-OCR-2, TeleOCR).
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
            provider=provider or settings.toolbox_page_ocr_provider,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

    async def transcribe(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/document.ocr.page:execute.

        Transcreve uma página inteira.

        Args:
            file_path: Caminho para a imagem da página.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            language: Idioma do documento (default: pt-BR).
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com markdown, finish (motivo de parada da geração) e provider.
        """
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{EXECUTE_PATH}"

        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "language": language,
                    "provider": self.provider,
                    "parameters": json.dumps({"language": language}),
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
                        "provider": self.provider,
                        "parameters": json.dumps({"language": language}),
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
                    f"OCR de página falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: OCR de página concluído (provider={}, finish={})",
                self.provider,
                result.get("document", {}).get("finish", "?"),
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao executar OCR de página via Toolbox: {e}"
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

__all__ = ["ToolboxPageOcrClient"]
