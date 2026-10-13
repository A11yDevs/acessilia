"""Table specialist agent — Agno tools over the docstruct table-specialist stack.

Dr.DocBench PR #125 (paper: generate-compare-adjudicate). Follows the
``FusionAgent`` pattern: each capability has a deterministic ``process_*``
method (pure, testable, no LLM) plus a thin tool envelope that returns
JSON-serializable dicts for the Agno agent.

Tools exposed:
- ``extract_table`` — pull the first ``<table>`` out of a VLM answer.
- ``normalize_table`` — evaluator-style table normalization.
- ``is_valid_table`` — structural validity check.
- ``build_candidates`` — assemble the candidate list (providers + generations).
- ``select_table`` — the medoid decision (self-consistency).
- ``select_greedy`` — the greedy decision, falling back to a provider when the
  greedy generation is ~identical to it.

The similarity (TEDS in the script) is injected: the agent defaults to a
character-overlap similarity so it works without the benchmark repository, and
callers can pass the real TEDS.

The deterministic methods live here so they can be unit-tested without Agno
installed; the tool envelopes are only wired into the Agno agent when the
optional stack is available (see ``backend.core.agno_support.build_agent``).
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from backend.core.agno_support import build_agent
from docstruct.fusion.table_specialist import (
    build_candidates,
    extract_table,
    is_valid_table,
    medoid_index,
    norm_table,
    select_greedy,
    select_table,
)


def overlap_similarity(a: str, b: str) -> float:
    """Similaridade de sobreposição de caracteres, usada quando nenhuma é injetada.

    Não substitui o TEDS: serve apenas para o caminho determinístico sem o
    repositório do benchmark.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    common = sum(1 for c in set(a) if c in b)
    return common / len(set(a) | set(b))


class TableSpecialistAgent:
    """Agno agent whose tools wrap the deterministic table-specialist stack."""

    def __init__(
        self,
        *,
        similarity: Callable[[str, str], float] | None = None,
        model: Any | None = None,
    ) -> None:
        self.similarity = similarity or overlap_similarity
        self.agent = build_agent(
            name="Agente Especialista de Tabela",
            instructions=(
                "Use as ferramentas fornecidas para escolher a melhor tabela "
                "entre os candidatos de forma determinística.",
                "Prefira as tabelas dos providers quando a geração do VLM não "
                "for claramente melhor.",
                "Nunca invente HTML: use somente os candidatos fornecidos.",
            ),
            tools=(
                self.extract_table,
                self.normalize_table,
                self.is_valid_table,
                self.build_candidates,
                self.select_table,
                self.select_greedy,
            ),
            model=model,
        )

    # ── Deterministic core (unit-testable without Agno) ──────────────────

    def process_extract_table(self, text: str) -> str:
        """Pull the first ``<table>`` out of a VLM answer."""
        return extract_table(text)

    def process_normalize_table(self, html: str) -> str:
        """Evaluator-style table normalization."""
        return norm_table(html)

    def process_is_valid_table(self, html: str) -> bool:
        """Structural validity check."""
        return is_valid_table(html)

    def process_build_candidates(
        self,
        record: dict[str, Any],
        greedy: str = "",
        samples: list[str] | None = None,
        max_chars: int = 0,
    ) -> list[tuple[str, str]]:
        """Assemble the candidate list (providers + generations)."""
        return build_candidates(record, greedy, samples, max_chars)

    def process_select_table(
        self,
        record: dict[str, Any],
        greedy: str = "",
        samples: list[str] | None = None,
        max_chars: int = 0,
    ) -> tuple[dict[str, Any] | None, Counter]:
        """The medoid decision (self-consistency)."""
        return select_table(record, greedy, samples, self.similarity, max_chars)

    def process_select_greedy(
        self,
        record: dict[str, Any],
        greedy: str = "",
        samples: list[str] | None = None,
        max_chars: int = 0,
    ) -> tuple[dict[str, Any] | None, Counter]:
        """The greedy decision, falling back to a provider when ~identical."""
        return select_greedy(record, greedy, samples, self.similarity, max_chars)

    def process_medoid_index(self, candidates: list[tuple[str, str]]) -> int:
        """Index of the medoid candidate."""
        return medoid_index(candidates, self.similarity)

    # ── Tool envelopes (JSON-serializable for Agno) ───────────────────────

    def extract_table(self, text: str) -> dict[str, Any]:
        """Extrai a primeira tabela HTML de uma resposta do VLM.

        Args:
            text (str): Resposta do VLM (pode conter cercas de código e texto extra).

        Returns:
            dict: ``{"html": str}`` (vazio quando não há tabela).
        """
        return {"html": self.process_extract_table(text)}

    def normalize_table(self, html: str) -> dict[str, Any]:
        """Normaliza uma tabela HTML no estilo do avaliador.

        Args:
            html (str): Tabela HTML.

        Returns:
            dict: ``{"html": str}``.
        """
        return {"html": self.process_normalize_table(html)}

    def is_valid_table(self, html: str) -> dict[str, Any]:
        """Verifica se uma tabela HTML é estruturalmente válida.

        Args:
            html (str): Tabela HTML.

        Returns:
            dict: ``{"valid": bool}``.
        """
        return {"valid": self.process_is_valid_table(html)}

    def build_candidates(
        self,
        record: dict[str, Any],
        greedy: str = "",
        samples: list[str] | None = None,
        max_chars: int = 0,
    ) -> dict[str, Any]:
        """Monta a lista de candidatos de tabela para um registro.

        Args:
            record (dict): Registro da fila (kind_d, kind_m, md_d, md_m).
            greedy (str): Geração greedy do VLM.
            samples (list[str] | None): Amostras adicionais do VLM.
            max_chars (int): Descarta gerações acima deste tamanho (0 = sem limite).

        Returns:
            dict: ``{"candidates": [{"name": str, "html": str}, ...]}``.
        """
        cands = self.process_build_candidates(record, greedy, samples, max_chars)
        return {"candidates": [{"name": n, "html": h} for n, h in cands]}

    def select_table(
        self,
        record: dict[str, Any],
        greedy: str = "",
        samples: list[str] | None = None,
        max_chars: int = 0,
    ) -> dict[str, Any]:
        """Seleciona a decisão do medoide para um registro de tabela.

        Args:
            record (dict): Registro da fila (kind_d, kind_m, md_d, md_m).
            greedy (str): Geração greedy do VLM.
            samples (list[str] | None): Amostras adicionais do VLM.
            max_chars (int): Descarta gerações acima deste tamanho (0 = sem limite).

        Returns:
            dict: ``{"decision": dict | None, "stats": dict}``.
        """
        decision, stats = self.process_select_table(record, greedy, samples, max_chars)
        return {"decision": decision, "stats": dict(stats)}

    def select_greedy(
        self,
        record: dict[str, Any],
        greedy: str = "",
        samples: list[str] | None = None,
        max_chars: int = 0,
    ) -> dict[str, Any]:
        """Seleciona a decisão da geração greedy.

        Args:
            record (dict): Registro da fila (kind_d, kind_m, md_d, md_m).
            greedy (str): Geração greedy do VLM.
            samples (list[str] | None): Amostras adicionais do VLM.
            max_chars (int): Descarta gerações acima deste tamanho (0 = sem limite).

        Returns:
            dict: ``{"decision": dict | None, "stats": dict}``.
        """
        decision, stats = self.process_select_greedy(record, greedy, samples, max_chars)
        return {"decision": decision, "stats": dict(stats)}
