"""Cliente especializado para as capacidades de adjudicação da Toolbox.

Encapsula:
- ``document.adjudicate.page`` — juiz pareado por VLM: vê a imagem da página e
  duas transcrições candidatas e diz qual é mais fiel (as duas ordens são
  perguntadas, para debiasing de posição).
- ``document.adjudicate.region`` — transcrição exata de um recorte de região,
  usada para derivar a decisão do differ (select/replace/drop).

Ambas vêm do Dr.DocBench (PR #125).
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

PAGE_CAPABILITY = "document.adjudicate.page"
REGION_CAPABILITY = "document.adjudicate.region"
PAGE_PATH = f"/v1/capabilities/{PAGE_CAPABILITY}:execute"
REGION_PATH = f"/v1/capabilities/{REGION_CAPABILITY}:execute"


class ToolboxAdjudicateClient(ToolboxClient):
    """Cliente para adjudicação por VLM via Acessilia Toolbox.

    Encapsula as capacidades:
    - document.adjudicate.page: juiz pareado entre duas transcrições de página
    - document.adjudicate.region: transcrição exata de um recorte de região
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
            provider=provider or settings.toolbox_adjudicate_provider,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

    async def _execute(
        self,
        path: str,
        capability: str,
        file_path: Path | None,
        artifact_id: str | None,
        payload: dict[str, Any],
        use_remote_cache: bool | None,
    ) -> dict[str, Any]:
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{path}"
        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "provider": self.provider,
                    "parameters": json.dumps(payload),
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
                        "parameters": json.dumps(payload),
                    }
                    if use_remote_cache is False:
                        params["no_cache"] = True
                    response = await self._client.post(
                        url, files=files, data=params
                    )

            _raise_for_error(response, capability)
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Adjudicação falhou na Toolbox: "
                    f"status={result.get('status')}"
                )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao executar adjudicação via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def judge_page(
        self,
        candidate_a: str,
        candidate_b: str,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        prompt: str = "base",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/document.adjudicate.page:execute.

        Julga qual das duas transcrições é mais fiel à página.

        Args:
            candidate_a: Primeira transcrição candidata.
            candidate_b: Segunda transcrição candidata.
            file_path: Caminho para a imagem da página.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            prompt: Variante do prompt ("base", "para" ou "err").
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com pB_ab, pA_ba e pB (probabilidade de B ser melhor, já
            corrigida do viés de posição).
        """
        result = await self._execute(
            PAGE_PATH,
            PAGE_CAPABILITY,
            file_path,
            artifact_id,
            {"candidate_a": candidate_a, "candidate_b": candidate_b, "prompt": prompt},
            use_remote_cache,
        )
        logger.info(
            "Toolbox: adjudicação de página concluída (pB={})",
            result.get("document", {}).get("pB", "?"),
        )
        return result

    async def transcribe_region(
        self,
        candidates: list[str],
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/document.adjudicate.region:execute.

        Transcreve exatamente o texto visível em um recorte de região.

        Args:
            candidates: Hipóteses de OCR para a região (dicas).
            file_path: Caminho para o recorte da região.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com text (transcrição exata; vazio quando não há texto legível).
        """
        result = await self._execute(
            REGION_PATH,
            REGION_CAPABILITY,
            file_path,
            artifact_id,
            {"candidates": candidates},
            use_remote_cache,
        )
        logger.info("Toolbox: transcrição de região concluída")
        return result

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

__all__ = ["ToolboxAdjudicateClient"]
