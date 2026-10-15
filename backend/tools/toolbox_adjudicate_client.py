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

from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxCapabilityClient

PAGE_CAPABILITY = "document.adjudicate.page"
REGION_CAPABILITY = "document.adjudicate.region"


class ToolboxAdjudicateClient(ToolboxCapabilityClient):
    """Cliente para adjudicação por VLM via Acessilia Toolbox.

    Encapsula as capacidades:
    - document.adjudicate.page: juiz pareado entre duas transcrições de página
    - document.adjudicate.region: transcrição exata de um recorte de região
    """

    provider_setting = "toolbox_adjudicate_provider"

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
            PAGE_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={
                "candidate_a": candidate_a,
                "candidate_b": candidate_b,
                "prompt": prompt,
            },
            no_cache=use_remote_cache is False,
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

        Args:
            candidates: Hipóteses de OCR para a região (dicas).
            file_path: Caminho para o recorte da região.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com text (transcrição exata; vazio quando não há texto legível).
        """
        result = await self._execute(
            REGION_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={"candidates": candidates},
            no_cache=use_remote_cache is False,
        )
        logger.info("Toolbox: transcrição de região concluída")
        return result


__all__ = ["ToolboxAdjudicateClient"]
