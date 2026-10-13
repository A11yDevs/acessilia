"""Adjudication agent — Agno tools over the docstruct adjudication protocol.

Dr.DocBench PR #125. Follows the ``FusionAgent`` pattern: each capability has a
deterministic ``process_*`` method (pure, testable, no LLM) plus a thin tool
envelope that returns JSON-serializable dicts for the Agno agent.

Tools exposed:
- ``route_page`` — per-page Docling/MinerU router (v0 or the component-aware v1).
- ``decide_from_transcription`` — turn a VLM exact transcription into a differ
  decision (select_a/select_b/replace/drop).
- ``filter_decisions`` — apply the notab/tight/sel safety filters.
- ``judge_pair`` — the pairwise VLM judge rule (new>0.5 or old>0.2).
- ``should_judge`` — whether two candidates diverge enough to be worth judging.
- ``select_page`` — the whole-page VLM pick when providers disagree.
- ``swap_low_agreement`` — the GT-free low-agreement page swap.
- ``oracle_headroom`` — per-page oracle and headroom (sizing before spending GPU).

The deterministic methods live here so they can be unit-tested without Agno
installed; the tool envelopes are only wired into the Agno agent when the
optional stack is available (see ``backend.core.agno_support.build_agent``).
"""
from __future__ import annotations

import difflib
from collections import Counter
from typing import Any

from backend.core.agno_support import build_agent
from docstruct.fusion.adjudication import (
    clean_transcription,
    decide,
    decide_v0,
    decide_v1,
    filter_decision,
)
from docstruct.fusion.judge import decide_pair, should_judge
from docstruct.fusion.oracle import oracle_page
from docstruct.fusion.page_select import (
    page_norm,
    select_by_agreement,
    swap_low_agreement_pages,
)


class AdjudicationAgent:
    """Agno agent whose tools wrap the deterministic adjudication protocol."""

    def __init__(
        self,
        *,
        model: Any | None = None,
    ) -> None:
        self.agent = build_agent(
            name="Agente de Adjudicação",
            instructions=(
                "Use as ferramentas fornecidas para decidir entre candidatos de "
                "forma determinística.",
                "Nunca invente transcrições: use somente o que as ferramentas "
                "produzem.",
                "Prefira a regra determinística quando a resposta do modelo for "
                "implausível.",
            ),
            tools=(
                self.route_page,
                self.decide_from_transcription,
                self.filter_decisions,
                self.judge_pair,
                self.should_judge,
                self.select_page,
                self.swap_low_agreement,
                self.oracle_headroom,
            ),
            model=model,
        )

    # ── Deterministic core (unit-testable without Agno) ──────────────────

    def process_route_page(
        self,
        docling_text: str,
        mineru_text: str,
        *,
        rule: str = "v1",
        table_pref: str = "mineru",
        formula_pref: str = "mineru",
        text_pref: str = "docling",
    ) -> tuple[str, str]:
        """Route a page between Docling and MinerU. Returns ``(choice, reason)``."""
        if rule == "v0":
            return decide_v0(docling_text, mineru_text)
        if rule == "v1":
            return decide_v1(
                docling_text,
                mineru_text,
                table_pref=table_pref,
                formula_pref=formula_pref,
                text_pref=text_pref,
            )
        raise ValueError(f"rule must be 'v0' or 'v1', got {rule!r}")

    def process_decide_from_transcription(
        self,
        record: dict[str, Any],
        transcription: str,
    ) -> dict[str, Any] | None:
        """Turn a VLM transcription into a differ decision (or None to keep the rule)."""
        stats: Counter = Counter()
        return decide(record, clean_transcription(transcription), stats)

    def process_filter_decisions(
        self,
        decisions: list[dict[str, Any]],
        records: list[dict[str, Any]],
        kind: str = "notab",
    ) -> list[dict[str, Any]]:
        """Apply a safety filter to the decisions, keyed by (page, i, j)."""
        key = {(r["page"], r["i"], r["j"]): r for r in records}
        out: list[dict[str, Any]] = []
        for x in decisions:
            record = key.get((x["page"], x["i"], x["j"]))
            if record is None:
                continue
            if filter_decision(x, record, kind):
                out.append(x)
        return out

    def process_judge_pair(
        self,
        p_new: float,
        p_old: float,
        new_thr: float = 0.5,
        old_thr: float = 0.2,
    ) -> bool:
        """True when the new candidate should replace the old one."""
        return decide_pair(p_new, p_old, new_thr, old_thr)

    def process_should_judge(
        self,
        a_text: str,
        b_text: str,
        max_ratio: float = 0.97,
    ) -> bool:
        """True when the two candidates diverge enough to be worth judging."""
        return should_judge(a_text, b_text, max_ratio)

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

    def process_oracle_headroom(
        self,
        gt_text: list[str],
        docling_blocks: list[str],
        mineru_blocks: list[str],
        differ_blocks: list[str],
    ) -> dict[str, float]:
        """Per-page oracle and headroom (oracle - differ)."""
        pred = {
            "docling": [page_norm(b) for b in docling_blocks],
            "mineru": [page_norm(b) for b in mineru_blocks],
            "differ": [page_norm(b) for b in differ_blocks],
        }
        return oracle_page(gt_text, pred, difflib.SequenceMatcher())

    # ── Tool envelopes (JSON-serializable for Agno) ───────────────────────

    def route_page(
        self,
        docling_text: str,
        mineru_text: str,
        rule: str = "v1",
        table_pref: str = "mineru",
        formula_pref: str = "mineru",
        text_pref: str = "docling",
    ) -> dict[str, Any]:
        """Roteia uma página entre Docling e MinerU.

        Args:
            docling_text (str): Markdown da página pelo Docling.
            mineru_text (str): Markdown da página pelo MinerU.
            rule (str): "v0" (tabela/fórmula decide) ou "v1" (component-aware).
            table_pref (str): Preferência quando ambos têm tabela.
            formula_pref (str): Preferência quando ambos têm fórmula.
            text_pref (str): Preferência de texto no caso default.

        Returns:
            dict: ``{"choice": str, "reason": str}``.
        """
        choice, reason = self.process_route_page(
            docling_text, mineru_text, rule=rule,
            table_pref=table_pref, formula_pref=formula_pref, text_pref=text_pref,
        )
        return {"choice": choice, "reason": reason}

    def decide_from_transcription(
        self,
        record: dict[str, Any],
        transcription: str,
    ) -> dict[str, Any]:
        """Converte a transcrição exata do VLM em uma decisão do differ.

        Args:
            record (dict): Registro da fila (page, i, j, md_d, md_m).
            transcription (str): Transcrição exata devolvida pelo VLM.

        Returns:
            dict: ``{"decision": dict | None}``; ``None`` mantém a regra determinística.
        """
        return {
            "decision": self.process_decide_from_transcription(record, transcription)
        }

    def filter_decisions(
        self,
        decisions: list[dict[str, Any]],
        records: list[dict[str, Any]],
        kind: str = "notab",
    ) -> dict[str, Any]:
        """Aplica um filtro de segurança às decisões do adjudicador.

        Args:
            decisions (list[dict]): Decisões (page, i, j, action, text).
            records (list[dict]): Registros da fila correspondentes.
            kind (str): "notab", "tight" ou "sel".

        Returns:
            dict: ``{"decisions": [...], "kept": int, "dropped": int}``.
        """
        kept = self.process_filter_decisions(decisions, records, kind)
        return {
            "decisions": kept,
            "kept": len(kept),
            "dropped": len(decisions) - len(kept),
        }

    def judge_pair(
        self,
        p_new: float,
        p_old: float,
        new_thr: float = 0.5,
        old_thr: float = 0.2,
    ) -> dict[str, Any]:
        """Decide se a candidata nova substitui a antiga (regra do juiz pareado).

        Args:
            p_new (float): P(nova melhor) do juiz atual.
            p_old (float): P(nova melhor) do juiz anterior.
            new_thr (float): Limiar do juiz atual (default 0.5).
            old_thr (float): Limiar do juiz anterior (default 0.2).

        Returns:
            dict: ``{"take_new": bool}``.
        """
        return {
            "take_new": self.process_judge_pair(p_new, p_old, new_thr, old_thr)
        }

    def should_judge(
        self,
        a_text: str,
        b_text: str,
        max_ratio: float = 0.97,
    ) -> dict[str, Any]:
        """Decide se duas candidatas divergem o bastante para valer julgar.

        Args:
            a_text (str): Texto da candidata A.
            b_text (str): Texto da candidata B.
            max_ratio (float): Acima deste ratio as candidatas são iguais (default 0.97).

        Returns:
            dict: ``{"should_judge": bool}``.
        """
        return {
            "should_judge": self.process_should_judge(a_text, b_text, max_ratio)
        }

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

    def oracle_headroom(
        self,
        gt_text: list[str],
        docling_blocks: list[str],
        mineru_blocks: list[str],
        differ_blocks: list[str],
    ) -> dict[str, float]:
        """Calcula o oráculo por bloco e a folga de uma página.

        Args:
            gt_text (list[str]): Blocos de texto do ground truth (normalizados).
            docling_blocks (list[str]): Blocos do Docling.
            mineru_blocks (list[str]): Blocos do MinerU.
            differ_blocks (list[str]): Blocos da saída do differ.

        Returns:
            dict: ``{"oracle": float, "headroom": float}``.
        """
        return self.process_oracle_headroom(
            gt_text, docling_blocks, mineru_blocks, differ_blocks
        )
