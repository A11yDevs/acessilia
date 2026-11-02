"""Page-level agent — Agno tools over the docstruct page-selection stack.

Dr.DocBench PR #125. Follows the ``FusionAgent`` pattern: each capability has a
deterministic ``process_*`` method (pure, testable, no LLM) plus a thin tool
envelope that returns JSON-serializable dicts for the Agno agent.

Tools exposed:
- ``fuse_page`` — fuse a whole-page VLM transcription with the differ output
  (``order`` / ``head`` / ``swap`` modes).
- ``select_page`` — pick the VLM page when Docling and MinerU disagree.
- ``swap_low_agreement`` — replace the fused page with an alternative source on
  the pages where the providers disagree the most.
- ``page_agreement`` — the difflib agreement between two pages.
- ``join_tail`` — join the trailing short blocks (the ``tj3`` rule).
- ``move_header_footer_to_end`` — the ground-truth header/footer convention.
- ``upscale_factor`` — the pure upscale decision for a page size.
- ``decide_orientation`` — the pure orientation decision from text boxes.

The deterministic methods live here so they can be unit-tested without Agno
installed; the tool envelopes are only wired into the Agno agent when the
optional stack is available (see ``backend.core.agno_support.build_agent``).
"""
from __future__ import annotations

from typing import Any

from backend.core.agno_support import build_agent
from docstruct.fusion.hf_end import move_hf_to_end
from docstruct.fusion.page_select import (
    fuse,
    page_agreement,
    select_by_agreement,
    swap_low_agreement_pages,
)
from docstruct.fusion.tailjoin import join_tail, tailjoin3
from docstruct.imaging.policy import decide_orientation, upscale_factor


class PageLevelAgent:
    """Agno agent whose tools wrap the deterministic page-level stack."""

    def __init__(
        self,
        *,
        model: Any | None = None,
    ) -> None:
        self.agent = build_agent(
            name="Agente de Página",
            instructions=(
                "Use as ferramentas fornecidas para decidir no nível da página "
                "de forma determinística.",
                "Preserve a ordem de leitura e as convenções de cauda do ground "
                "truth.",
                "Nunca invente texto: use somente o que as ferramentas produzem.",
            ),
            tools=(
                self.fuse_page,
                self.select_page,
                self.swap_low_agreement,
                self.page_agreement,
                self.join_tail,
                self.move_header_footer_to_end,
                self.upscale_factor,
                self.decide_orientation,
            ),
            model=model,
        )

    # ── Deterministic core (unit-testable without Agno) ──────────────────

    def process_fuse_page(
        self,
        a_text: str,
        b_text: str,
        mode: str = "order",
        sim: float = 0.6,
        tables: bool = False,
    ) -> str:
        """Fuse a whole-page VLM transcription (B) with the differ output (A)."""
        return fuse(a_text, b_text, mode, sim, tables)

    def process_select_page(
        self,
        a_text: str,
        vlm_text: str,
        docling_text: str,
        mineru_text: str,
        finish: str | None,
        dm: float = 0.6,
        ab: float = 0.0,
    ) -> tuple[str, bool]:
        """Decide whether the VLM page replaces the differ output."""
        return select_by_agreement(
            a_text, vlm_text, docling_text, mineru_text, finish, dm, ab
        )

    def process_swap_low_agreement(
        self,
        base_text: str,
        alt_text: str | None,
        docling_text: str,
        mineru_text: str,
        agree_thr: float = 0.45,
        min_alt_frac: float = 0.3,
    ) -> tuple[str, bool]:
        """Decide whether the alternative source replaces the fused page."""
        return swap_low_agreement_pages(
            base_text, alt_text, docling_text, mineru_text, agree_thr, min_alt_frac
        )

    def process_page_agreement(self, a_text: str, b_text: str) -> float:
        """The difflib agreement between two pages."""
        return page_agreement(a_text, b_text)

    def process_join_tail(
        self,
        blocks: list[str],
        mode: str = "end",
        max_len: int = 50,
        k: int = 3,
        position: str | None = None,
        bot: str = "keep",
    ) -> list[str]:
        """Join the trailing short blocks, plain mode or the ``tj3`` rule."""
        if position is not None:
            return tailjoin3(blocks, position, max_len, k, bot)
        return join_tail(blocks, mode, max_len, k)

    def process_move_header_footer_to_end(
        self,
        elements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Move Page-header/Page-footer elements to the end (GT convention)."""
        return move_hf_to_end(elements)

    def process_upscale_factor(self, width: int, height: int) -> float:
        """The pure upscale factor for a page of ``width`` x ``height``."""
        return upscale_factor(width, height)

    def process_decide_orientation(
        self,
        boxes: list,
        scores: dict[int, tuple[float, int]] | None = None,
    ) -> int:
        """The pure orientation decision from text boxes and OCR scores."""
        return decide_orientation(boxes, scores)

    # ── Tool envelopes (JSON-serializable for Agno) ───────────────────────

    def fuse_page(
        self,
        a_text: str,
        b_text: str,
        mode: str = "order",
        sim: float = 0.6,
        tables: bool = False,
    ) -> dict[str, Any]:
        """Funde a transcrição VLM de página inteira com a saída do differ.

        Args:
            a_text (str): Saída do differ (carrega as convenções de ordem e cauda).
            b_text (str): Transcrição VLM da página inteira.
            mode (str): "order", "head" ou "swap".
            sim (float): Similaridade mínima para casar blocos (default 0.6).
            tables (bool): Permitir troca de tabelas no modo "swap".

        Returns:
            dict: ``{"text": str}``.
        """
        return {"text": self.process_fuse_page(a_text, b_text, mode, sim, tables)}

    def select_page(
        self,
        a_text: str,
        vlm_text: str,
        docling_text: str,
        mineru_text: str,
        finish: str | None,
        dm: float = 0.6,
        ab: float = 0.0,
    ) -> dict[str, Any]:
        """Decide se a página VLM substitui a saída do differ.

        Args:
            a_text (str): Saída do differ para a página.
            vlm_text (str): Transcrição VLM da página inteira.
            docling_text (str): Texto do Docling (para a concordância).
            mineru_text (str): Texto do MinerU (para a concordância).
            finish (str | None): Motivo de parada da geração VLM ("stop" = completa).
            dm (float): Concordância Docling/MinerU abaixo da qual vale a VLM.
            ab (float): Concordância mínima com a VLM para trocar sem ser mais longa.

        Returns:
            dict: ``{"text": str, "swapped": bool}``.
        """
        text, swapped = self.process_select_page(
            a_text, vlm_text, docling_text, mineru_text, finish, dm, ab
        )
        return {"text": text, "swapped": swapped}

    def swap_low_agreement(
        self,
        base_text: str,
        alt_text: str | None,
        docling_text: str,
        mineru_text: str,
        agree_thr: float = 0.45,
        min_alt_frac: float = 0.3,
    ) -> dict[str, Any]:
        """Decide se a fonte alternativa substitui a página fundida.

        Args:
            base_text (str): Página fundida atual.
            alt_text (str | None): Página da fonte alternativa (None = indisponível).
            docling_text (str): Texto do Docling (para a concordância).
            mineru_text (str): Texto do MinerU (para a concordância).
            agree_thr (float): Concordância abaixo da qual a alternativa substitui.
            min_alt_frac (float): Fração mínima de comprimento da alternativa.

        Returns:
            dict: ``{"text": str, "swapped": bool}``.
        """
        text, swapped = self.process_swap_low_agreement(
            base_text, alt_text, docling_text, mineru_text, agree_thr, min_alt_frac
        )
        return {"text": text, "swapped": swapped}

    def page_agreement(self, a_text: str, b_text: str) -> dict[str, Any]:
        """Calcula a concordância entre duas páginas.

        Args:
            a_text (str): Texto da primeira página.
            b_text (str): Texto da segunda página.

        Returns:
            dict: ``{"agreement": float}`` em [0, 1].
        """
        return {"agreement": self.process_page_agreement(a_text, b_text)}

    def join_tail(
        self,
        blocks: list[str],
        mode: str = "end",
        max_len: int = 50,
        k: int = 3,
        position: str | None = None,
        bot: str = "keep",
    ) -> dict[str, Any]:
        """Junta os blocos curtos finais (cabeçalho/rodapé/número de página).

        Args:
            blocks (list[str]): Blocos da página, em ordem.
            mode (str): "num", "end" ou "any" (usado quando ``position`` é None).
            max_len (int): Comprimento máximo de um bloco da cauda (default 50).
            k (int): Número máximo de blocos na cauda (default 3).
            position (str | None): "top"/"bot" do número de página; ativa a regra tj3.
            bot (str): Com ``position="bot"``, "keep" deixa a cauda e "hdr" move os números ao fim.

        Returns:
            dict: ``{"blocks": [...]}``.
        """
        return {
            "blocks": self.process_join_tail(
                blocks, mode, max_len, k, position, bot
            )
        }

    def move_header_footer_to_end(
        self,
        elements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Move elementos de cabeçalho/rodapé para o fim da página.

        Args:
            elements (list[dict]): Elementos de layout (category, text).

        Returns:
            dict: ``{"elements": [...]}``.
        """
        return {"elements": self.process_move_header_footer_to_end(elements)}

    def upscale_factor(self, width: int, height: int) -> dict[str, Any]:
        """Calcula o fator de upscale de uma página antes do OCR.

        Args:
            width (int): Largura da página em pixels.
            height (int): Altura da página em pixels.

        Returns:
            dict: ``{"factor": float}`` (2.0, 1.5 ou 1.0).
        """
        return {"factor": self.process_upscale_factor(width, height)}

    def decide_orientation(
        self,
        boxes: list,
        scores: dict[int, tuple[float, int]] | None = None,
    ) -> dict[str, Any]:
        """Decide o ângulo de correção de orientação de uma página.

        Args:
            boxes (list): Caixas de texto no formato de cantos do RapidOCR.
            scores (dict | None): ``{ângulo: (score, n_caixas)}`` do OCR a 90/270.

        Returns:
            dict: ``{"angle": int}`` (0, 90, 180 ou 270).
        """
        return {"angle": self.process_decide_orientation(boxes, scores)}
