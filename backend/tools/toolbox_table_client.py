"""Cliente especializado para a capacidade table.recognize da Toolbox.

Regera uma tabela como HTML a partir do recorte dela, com um modelo de visão:
uma geração greedy mais amostras com semente. É a etapa de geração do
especialista de tabelas do Dr.DocBench (``vlm_tables.py``); a seleção entre as
gerações e as tabelas dos providers fica com quem chama.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxCapabilityClient

CAPABILITY = "table.recognize"


class ToolboxTableClient(ToolboxCapabilityClient):
    """Cliente para reconhecimento de tabelas por VLM via Acessilia Toolbox."""

    provider_key = "toolbox_table_provider"

    async def recognize(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        hints: list[str] | None = None,
        use_hints: bool = True,
        header_cells: str = "th",
        samples: int = 3,
        temperature: float = 0.7,
        top_p: float = 0.95,
        seed: int = 0,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/table.recognize:execute.

        Args:
            file_path: Caminho para o recorte da tabela.
            artifact_id: ID do artifact previamente armazenado na Toolbox.
            hints: Tabelas dos providers em HTML, mostradas ao modelo como dicas.
            use_hints: Se False, o prompt não mostra as dicas.
            header_cells: Tag pedida para o cabeçalho ("th" ou "td").
            samples: Quantidade de amostras além da geração greedy.
            temperature, top_p, seed: Amostragem das amostras.
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Envelope da Toolbox; ``document`` segue ``table-candidates@1``
            (``greedy`` e ``samples`` com ``text`` e ``finish``).
        """
        result = await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={
                "hints": list(hints or []),
                "use_hints": use_hints,
                "header_cells": header_cells,
                "samples": samples,
                "temperature": temperature,
                "top_p": top_p,
                "seed": seed,
            },
            no_cache=use_remote_cache is False,
        )
        document = result.get("document", {})
        logger.info(
            "Toolbox: tabela reconhecida (1 greedy + {} amostras, provider={})",
            len(document.get("samples", [])),
            self.provider,
        )
        return result


__all__ = ["ToolboxTableClient"]
