"""Cliente especializado para a capacidade image.page.orient da Toolbox.

Detecta a rotação de uma página (0/90/180/270) a partir da imagem. O sufixo
``+rot`` está em ambas as fontes do melhor resultado confirmado no leaderboard
do Dr.DocBench (PR #125).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxCapabilityClient

CAPABILITY = "image.page.orient"


class ToolboxOrientationClient(ToolboxCapabilityClient):
    """Cliente para detecção de orientação via Acessilia Toolbox.

    Encapsula a capacidade image.page.orient, que devolve o ângulo
    de correção (0/90/180/270) de uma página.
    """

    provider_setting = "toolbox_orientation_provider"

    async def detect(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        return_image: bool = False,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/image.page.orient:execute.

        Args:
            file_path: Caminho para a imagem da página.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            return_image: Se True, inclui a imagem rotacionada no resultado.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com angle (0/90/180/270), confidence, stage e as dimensões
            original e orientada.
        """
        result = await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={"return_image": return_image},
            no_cache=use_remote_cache is False,
        )
        logger.info(
            "Toolbox: orientação detectada (angle={})",
            result.get("document", {}).get("angle", "?"),
        )
        return result


__all__ = ["ToolboxOrientationClient"]
