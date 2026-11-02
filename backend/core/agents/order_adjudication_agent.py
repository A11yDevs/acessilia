"""Order adjudication agent — Agno tools over the reading-order decision stack.

Dr.DocBench PR #125. Follows the ``FusionAgent`` pattern: each capability has a
deterministic ``process_*`` method (pure, testable, no LLM) plus a thin tool
envelope that returns JSON-serializable dicts for the Agno agent.

Tools exposed:
- ``parse_order`` — parse the VLM's comma-separated block numbers into a
  permutation (deduplicated, out-of-range dropped).
- ``kendall_tau`` — Kendall tau between two orders.
- ``complete_order`` — append the missing blocks in skeleton order.
- ``adjudicate_order`` — the ``vlm_order`` decision: the VLM permutation as is,
  plus the ``sel`` variant where the VLM only judges between the skeleton order
  and the XY-cut order (closest by Kendall tau).
- ``refine_reading_order`` — the XY-cut permutation over normalized boxes.

The deterministic methods live here so they can be unit-tested without Agno
installed; the tool envelopes are only wired into the Agno agent when the
optional stack is available (see ``backend.core.agno_support.build_agent``).
"""
from __future__ import annotations

import re
from typing import Any

from backend.core.agno_support import build_agent
from docstruct.fusion.xycut import xycut_order

# Fração mínima de blocos que o VLM precisa listar para a resposta valer.
DEFAULT_MIN_COVER = 0.8

_NUMBER_RE = re.compile(r"\d+")


def parse_order(answer: str, n: int) -> list[int]:
    """Parse the VLM answer into a 0-based permutation of ``n`` blocks.

    Numbers are read in order, converted to 0-based indices, deduplicated and
    dropped when out of range.
    """
    seen: set[int] = set()
    perm: list[int] = []
    for x in _NUMBER_RE.findall(answer or ""):
        k = int(x) - 1
        if 0 <= k < n and k not in seen:
            seen.add(k)
            perm.append(k)
    return perm


def kendall_tau(p: list[int], q: list[int]) -> float:
    """Kendall tau between two orders (lists of the same items)."""
    pos = {x: r for r, x in enumerate(q)}
    r = [pos[x] for x in p]
    n = len(r)
    if n < 2:
        return 1.0
    c = sum(1 if r[i] < r[j] else -1 for i in range(n) for j in range(i + 1, n))
    return c / (n * (n - 1) / 2)


def complete_order(perm: list[int], n: int) -> list[int]:
    """Append the blocks missing from ``perm`` in skeleton order."""
    seen = set(perm)
    return perm + [k for k in range(n) if k not in seen]


class OrderAdjudicationAgent:
    """Agno agent whose tools wrap the deterministic reading-order decisions."""

    def __init__(
        self,
        *,
        model: Any | None = None,
    ) -> None:
        self.agent = build_agent(
            name="Agente de Ordem de Leitura",
            instructions=(
                "Use as ferramentas fornecidas para decidir a ordem de leitura "
                "de forma determinística.",
                "Prefira a ordem do skeleton quando o VLM não a superar "
                "claramente.",
                "Nunca invente blocos: use somente os índices fornecidos.",
            ),
            tools=(
                self.parse_order,
                self.kendall_tau,
                self.complete_order,
                self.adjudicate_order,
                self.refine_reading_order,
            ),
            model=model,
        )

    # ── Deterministic core (unit-testable without Agno) ──────────────────

    def process_parse_order(self, answer: str, n: int) -> list[int]:
        """Parse the VLM answer into a 0-based permutation."""
        return parse_order(answer, n)

    def process_kendall_tau(self, p: list[int], q: list[int]) -> float:
        """Kendall tau between two orders."""
        return kendall_tau(p, q)

    def process_complete_order(self, perm: list[int], n: int) -> list[int]:
        """Append the missing blocks in skeleton order."""
        return complete_order(perm, n)

    def process_adjudicate_order(
        self,
        answer: str,
        n: int,
        xy: list[int],
        min_cover: float = DEFAULT_MIN_COVER,
    ) -> dict[str, Any]:
        """Decide the reading order for one page.

        Returns ``{"status", "vlm", "sel"}`` where ``status`` is one of
        ``"no-answer"``, ``"low-cover"``, ``"vlm=skeleton"`` or ``"vlm-reorder"``.
        ``vlm`` is the VLM permutation (None when the answer is unusable) and
        ``sel`` is the chosen order when the VLM only judges between the
        skeleton and the XY-cut (None when the skeleton wins).
        """
        perm = parse_order(answer, n)
        if len(perm) < min_cover * n:
            return {"status": "low-cover", "vlm": None, "sel": None}
        perm = complete_order(perm, n)
        ident = list(range(n))
        if perm == ident:
            return {"status": "vlm=skeleton", "vlm": None, "sel": None}
        sel = None
        if xy != ident and kendall_tau(perm, xy) > kendall_tau(perm, ident):
            sel = xy
        return {"status": "vlm-reorder", "vlm": perm, "sel": sel}

    def process_refine_reading_order(self, boxes: list[list[float]]) -> list[int]:
        """The XY-cut reading-order permutation of normalized boxes."""
        return xycut_order(boxes)

    # ── Tool envelopes (JSON-serializable for Agno) ───────────────────────

    def parse_order(self, answer: str, n: int) -> dict[str, Any]:
        """Converte a resposta do VLM em uma permutação 0-based dos blocos.

        Args:
            answer (str): Resposta do VLM (números separados por vírgula).
            n (int): Número de blocos da página.

        Returns:
            dict: ``{"order": [int, ...]}``.
        """
        return {"order": self.process_parse_order(answer, n)}

    def kendall_tau(self, p: list[int], q: list[int]) -> dict[str, Any]:
        """Calcula o tau de Kendall entre duas ordens.

        Args:
            p (list[int]): Primeira ordem (permutação dos mesmos itens).
            q (list[int]): Segunda ordem.

        Returns:
            dict: ``{"tau": float}`` em [-1, 1].
        """
        return {"tau": self.process_kendall_tau(p, q)}

    def complete_order(self, perm: list[int], n: int) -> dict[str, Any]:
        """Completa uma permutação com os blocos faltantes na ordem do skeleton.

        Args:
            perm (list[int]): Permutação parcial (0-based).
            n (int): Número total de blocos.

        Returns:
            dict: ``{"order": [int, ...]}``.
        """
        return {"order": self.process_complete_order(perm, n)}

    def adjudicate_order(
        self,
        answer: str,
        n: int,
        xy: list[int],
        min_cover: float = DEFAULT_MIN_COVER,
    ) -> dict[str, Any]:
        """Decide a ordem de leitura de uma página a partir da resposta do VLM.

        Args:
            answer (str): Resposta do VLM (números separados por vírgula).
            n (int): Número de blocos da página.
            xy (list[int]): Ordem XY-cut proposta para a página.
            min_cover (float): Fração mínima de blocos que o VLM deve listar.

        Returns:
            dict: ``{"status": str, "vlm": list[int] | None, "sel": list[int] | None}``.
        """
        return self.process_adjudicate_order(answer, n, xy, min_cover)

    def refine_reading_order(self, boxes: list[list[float]]) -> dict[str, Any]:
        """Calcula a ordem de leitura XY-cut de caixas normalizadas.

        Args:
            boxes (list[list[float]]): Caixas ``[x0, y0, x1, y1]`` no quadrado unitário.

        Returns:
            dict: ``{"order": [int, ...]}``.
        """
        return {"order": self.process_refine_reading_order(boxes)}
