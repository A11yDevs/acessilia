"""Cliente especializado para a capacidade image.page.orient da Toolbox.

Detecta a rotação de uma página (0/90/180/270) a partir da imagem. O sufixo
``+rot`` está em ambas as fontes do melhor resultado confirmado no leaderboard
do Dr.DocBench (PR #125).
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

CAPABILITY = "image.page.orient"
EXECUTE_PATH = f"/v1/capabilities/{CAPABILITY}:execute"


class ToolboxOrientationClient(ToolboxClient):
    """Cliente para detecção de orientação via Acessilia Toolbox.

    Encapsula a capacidade image.page.orient, que devolve o ângulo
    de correção (0/90/180/270) de uma página.

    Args:
        file_path: Caminho para a imagem da página.
        artifact_id: ID do artifact previamente armazenado na Toolbox.
        return_image: Se True, pede também a imagem já rotacionada.
        use_remote_cache: Se False, força re-processamento remoto.

    Returns:
        Dict com angle (0/90/180/270), confidence, stage e as dimensões
        original e orientada.
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
            provider=provider or settings.toolbox_orientation_provider,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

    async def detect(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        return_image: bool = False,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/image.page.orient:execute.

        Detecta o ângulo de correção de uma página.

        Args:
            file_path: Caminho para a imagem da página.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            return_image: Se True, inclui a imagem rotacionada no resultado.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com angle (0/90/180/270), confidence, stage e as dimensões
            original e orientada.
        """
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{EXECUTE_PATH}"
        parameters = json.dumps({"return_image": return_image})

        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "provider": self.provider,
                    "parameters": parameters,
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
                        "parameters": parameters,
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
                    f"Detecção de orientação falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: orientação detectada (angle={})",
                result.get("document", {}).get("angle", "?"),
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao detectar orientação via Toolbox: {e}"
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

__all__ = ["ToolboxOrientationClient"]
