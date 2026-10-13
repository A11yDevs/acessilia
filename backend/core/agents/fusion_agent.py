"""Fusion agent — Agno tools over the docstruct fusion/validation stack.

Phase 5 of the docstruct plan. Follows the ``InformationalStructuralAgent``
pattern: each capability has a deterministic ``process_*`` method (pure,
testable, no LLM) plus a thin tool envelope that returns JSON-serializable
dicts for the Agno agent.

Tools exposed:
- ``fuse_providers`` — merge two toolbox providers via ``docstruct.fusion``.
- ``audit_document`` — run the canonical-document audit (validation findings).
- ``classify_block`` — classify a region/block via ``docstruct.regions``.
- ``needs_reinfer`` — decide whether a region needs re-inference (vision or
  orientation correction).
- ``chunk_verse`` — split verse/record blocks (Dr.DocBench PR #125).
- ``extract_line_numbers`` — pull marginal verse line numbers into own blocks.
- ``join_tail`` — join the trailing short blocks (header/footer/page number).
- ``guard_repetition`` — cut degenerate generation loops.
- ``normalize_text`` — deterministic text cleanups (ligatures, hyphen, NBSP).
- ``normalize_formula`` — LaTeX normalization.
- ``refine_reading_order`` — XY-cut reading order over normalized boxes.
- ``move_header_footer_to_end`` — the ground-truth header/footer convention.

The deterministic methods live here so they can be unit-tested without Agno
installed; the tool envelopes are only wired into the Agno agent when the
optional stack is available (see ``backend.core.agno_support.build_agent``).

Design note (tool envelope vs core): the Agno tool envelopes intentionally do
NOT serialize ``image_bytes`` — they reconstruct a ``Region`` with
``image_bytes=None``. This is a conscious decision: binary payloads should not
cross tool-call boundaries. For future multimodal decisions, pass a persistent
reference (``artifact_id`` / ``image_ref`` / ``crop_path`` / object-storage URI)
instead of raw bytes.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.core.agno_support import build_agent
from docstruct.fusion.hf_end import move_hf_to_end
from docstruct.fusion.line_numbers import extract_line_numbers
from docstruct.fusion.repetition import collapse, guard_page
from docstruct.fusion.tailjoin import join_tail, tailjoin3
from docstruct.fusion.types import DiffBlock
from docstruct.fusion.verse import verse_blocks
from docstruct.fusion.xycut import xycut_order
from docstruct.regions.classify import (
    classify_region,
    region_needs_vision,
)
from docstruct.text.latex import normalize_latex
from docstruct.text.norm_fix import norm_fix
from docstruct.types import Region
from docstruct.validation import audit_canonical_document


class FusionAgent:
    """Agno agent whose tools wrap the deterministic fusion/audit stack."""

    def __init__(
        self,
        *,
        model: Any | None = None,
    ) -> None:
        self.agent = build_agent(
            name="Agente de Fusão",
            instructions=(
                "Use as ferramentas fornecidas para fundir, auditar e "
                "classificar documentos de forma determinística.",
                "Não invente resultados: retorne somente o que as ferramentas "
                "produzem.",
                "Prefira a fusão dual-provider quando a qualidade do texto "
                "for crítica.",
            ),
            tools=(
                self.fuse_providers,
                self.audit_document,
                self.classify_block,
                self.needs_reinfer,
                self.chunk_verse,
                self.extract_line_numbers,
                self.join_tail,
                self.guard_repetition,
                self.normalize_text,
                self.normalize_formula,
                self.refine_reading_order,
                self.move_header_footer_to_end,
            ),
            model=model,
        )

    # ── Deterministic core (unit-testable without Agno) ──────────────────

    def process_fuse_providers(
        self,
        document_path: Path | str,
        *,
        language: str = "pt-BR",
        primary_provider: str | None = None,
        secondary_provider: str | None = None,
    ) -> dict[str, Any]:
        """Merge two toolbox providers into a single fused payload.

        Delegates to ``backend.pipeline.fusion.extract_fused`` (the only layer
        that knows both the toolbox and the lib). Returns the fused payload in
        the same shape as ``extract_structure``.
        """
        from backend.pipeline.fusion import extract_fused

        return asyncio.run(
            extract_fused(
                Path(document_path),
                language=language,
                primary_provider=primary_provider,
                secondary_provider=secondary_provider,
            )
        )

    def process_audit_document(
        self,
        document: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Audit a canonical document and return grouped findings."""
        return audit_canonical_document(document)

    def process_classify_block(
        self,
        region: Region,
    ) -> str:
        """Classify a region into a docstruct category."""
        return classify_region(region)

    def process_needs_reinfer(
        self,
        region: Region,
    ) -> bool:
        """Decide whether a region needs re-inference (vision or orientation)."""
        classification = classify_region(region)
        return region_needs_vision(classification)

    # ── Deterministic post-processing (Dr.DocBench PR #125) ──────────────

    @staticmethod
    def _to_blocks(blocks: list[dict[str, Any]]) -> list[DiffBlock]:
        return [
            DiffBlock(
                md=b.get("md", b.get("text", "")),
                kind=b.get("kind", "text"),
                box=tuple(b["box"]) if b.get("box") else None,
                text=b.get("text", b.get("md", "")),
                type=b.get("type", "text"),
                role=b.get("role"),
            )
            for b in blocks
        ]

    def process_chunk_verse(
        self,
        blocks: list[dict[str, Any]],
        max_chars: int = 300,
        kind: str = "records",
    ) -> dict[str, Any]:
        """Split verse/record blocks into chunks the evaluator can re-group."""
        from collections import Counter

        stats: Counter = Counter()
        out = verse_blocks(self._to_blocks(blocks), stats, "agent", max_chars, kind)
        return {
            "blocks": [
                {"md": b.md, "kind": b.kind, "box": list(b.box) if b.box else None,
                 "text": b.text, "type": b.type, "role": b.role, "verse": b.verse}
                for b in out
            ],
            "stats": dict(stats),
        }

    def process_extract_line_numbers(
        self,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Move marginal verse line numbers into their own blocks."""
        from collections import Counter

        stats: Counter = Counter()
        out = extract_line_numbers(self._to_blocks(blocks), stats, "agent")
        return {
            "blocks": [
                {"md": b.md, "kind": b.kind, "box": list(b.box) if b.box else None,
                 "text": b.text, "type": b.type, "role": b.role,
                 "verse_nums": b.verse_nums}
                for b in out
            ],
            "stats": dict(stats),
        }

    def process_join_tail(
        self,
        blocks: list[str],
        mode: str = "end",
        max_len: int = 50,
        k: int = 3,
        position: str | None = None,
        bot: str = "keep",
    ) -> list[str]:
        """Join the trailing short blocks (header/footer/page number).

        With ``position`` set, applies the position-conditioned rule ``tj3``;
        otherwise applies the plain ``join_tail`` mode.
        """
        if position is not None:
            return tailjoin3(blocks, position, max_len, k, bot)
        return join_tail(blocks, mode, max_len, k)

    def process_guard_repetition(
        self,
        text: str,
        docling_text: str = "",
        vlm_text: str = "",
        reps: int = 5,
        max_n: int = 12,
        blank: bool = False,
    ) -> dict[str, Any]:
        """Cut degenerate generation loops and optionally blank pages."""
        out, cut, was_blank = guard_page(
            text, docling_text, vlm_text, reps=reps, max_n=max_n, blank=blank
        )
        return {"text": out, "tokens_cut": cut, "was_blank": was_blank}

    def process_normalize_text(self, text: str) -> str:
        """Apply the deterministic text cleanups (ligatures, hyphen, NBSP)."""
        return norm_fix(text)

    def process_normalize_formula(self, latex: str) -> str:
        """Normalize a LaTeX formula (delimiters, Unicode symbols, spacing)."""
        return normalize_latex(latex)

    def process_refine_reading_order(
        self,
        boxes: list[list[float]],
    ) -> list[int]:
        """Return the XY-cut reading-order permutation of normalized boxes."""
        return xycut_order(boxes)

    def process_move_header_footer_to_end(
        self,
        elements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Move Page-header/Page-footer elements to the end (GT convention)."""
        return move_hf_to_end(elements)

    # ── Tool envelopes (JSON-serializable for Agno) ───────────────────────

    def fuse_providers(
        self,
        document_path: str,
        language: str = "pt-BR",
        primary_provider: str | None = None,
        secondary_provider: str | None = None,
    ) -> dict[str, Any]:
        """Funde dois providers de extração em um único payload.

        Args:
            document_path (str): Caminho do documento a processar.
            language (str): Idioma do documento (default "pt-BR").
            primary_provider (str | None): Provider primário (default: config).
            secondary_provider (str | None): Provider secundário (default: config).

        Returns:
            dict: Payload fundido com ``document.elements`` e ``fusion_stats``.
        """
        return self.process_fuse_providers(
            Path(document_path),
            language=language,
            primary_provider=primary_provider,
            secondary_provider=secondary_provider,
        )

    def audit_document(
        self,
        document: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Audita um documento canônico e retorna achados agrupados.

        Args:
            document (dict): Documento canônico (schema_version, sections, ...).

        Returns:
            dict: Mapeamento ``{"ERROR": [...], "WARNING": [...], "INFO": [...]}``.
        """
        return self.process_audit_document(document)

    def classify_block(
        self,
        region: dict[str, Any],
    ) -> dict[str, Any]:
        """Classifica uma região em uma categoria docstruct.

        Args:
            region (dict): Região serializada (bbox, type, text, confidence,
                page_num, metadata).

        Returns:
            dict: ``{"classification": str, "needs_vision": bool}``.
        """
        parsed = Region(
            bbox=tuple(region["bbox"]),
            type=region.get("type", "unknown"),
            text=region.get("text", ""),
            image_bytes=None,
            confidence=region.get("confidence", 0.0),
            page_num=region.get("page_num", 1),
            metadata=region.get("metadata", {}),
        )
        classification = self.process_classify_block(parsed)
        return {
            "classification": classification,
            "needs_vision": region_needs_vision(classification),
        }

    def needs_reinfer(
        self,
        region: dict[str, Any],
    ) -> dict[str, Any]:
        """Decide se uma região precisa de re-inferência.

        Args:
            region (dict): Região serializada (mesmo formato de ``classify_block``).

        Returns:
            dict: ``{"needs_reinfer": bool, "reason": str}``.
        """
        parsed = Region(
            bbox=tuple(region["bbox"]),
            type=region.get("type", "unknown"),
            text=region.get("text", ""),
            image_bytes=None,
            confidence=region.get("confidence", 0.0),
            page_num=region.get("page_num", 1),
            metadata=region.get("metadata", {}),
        )
        classification = self.process_classify_block(parsed)
        needs = self.process_needs_reinfer(parsed)
        reason = (
            f"classificação '{classification}' requer re-inferência"
            if needs
            else "região já processável"
        )
        return {"needs_reinfer": needs, "reason": reason}

    def chunk_verse(
        self,
        blocks: list[dict[str, Any]],
        max_chars: int = 300,
        kind: str = "records",
    ) -> dict[str, Any]:
        """Divide blocos de verso/registro em pedaços reagrupáveis pelo avaliador.

        Args:
            blocks (list[dict]): Blocos serializados (md, kind, box, text, type).
            max_chars (int): Comprimento máximo de cada pedaço (default 300).
            kind (str): "records" preserva verso real inteiro; "all" divide tudo.

        Returns:
            dict: ``{"blocks": [...], "stats": {...}}``.
        """
        return self.process_chunk_verse(blocks, max_chars, kind)

    def extract_line_numbers(
        self,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Move números de linha marginais de verso para blocos próprios.

        Args:
            blocks (list[dict]): Blocos serializados (md, kind, box, text, type).

        Returns:
            dict: ``{"blocks": [...], "stats": {...}}``.
        """
        return self.process_extract_line_numbers(blocks)

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

    def guard_repetition(
        self,
        text: str,
        docling_text: str = "",
        vlm_text: str = "",
        reps: int = 5,
        max_n: int = 12,
        blank: bool = False,
    ) -> dict[str, Any]:
        """Corta repetição degenerada (loops de geração) e detecta página branca.

        Args:
            text (str): Texto da página a proteger.
            docling_text (str): Texto do Docling (referência de repetição legítima).
            vlm_text (str): Texto da VLM (referência e detecção de página branca).
            reps (int): Repetições mínimas para cortar (default 5).
            max_n (int): Tamanho máximo do n-grama (default 12).
            blank (bool): Esvaziar páginas em branco detectadas.

        Returns:
            dict: ``{"text": str, "tokens_cut": int, "was_blank": bool}``.
        """
        return self.process_guard_repetition(
            text, docling_text, vlm_text, reps, max_n, blank
        )

    def normalize_text(self, text: str) -> dict[str, Any]:
        """Aplica as limpezas determinísticas de texto.

        Args:
            text (str): Texto a limpar (ligaduras, hífen suave, NBSP, espaços).

        Returns:
            dict: ``{"text": str}``.
        """
        return {"text": self.process_normalize_text(text)}

    def normalize_formula(self, latex: str) -> dict[str, Any]:
        """Normaliza uma fórmula LaTeX.

        Args:
            latex (str): Fórmula LaTeX (com ou sem delimitadores).

        Returns:
            dict: ``{"latex": str}``.
        """
        return {"latex": self.process_normalize_formula(latex)}

    def refine_reading_order(
        self,
        boxes: list[list[float]],
    ) -> dict[str, Any]:
        """Calcula a ordem de leitura XY-cut de caixas normalizadas.

        Args:
            boxes (list[list[float]]): Caixas ``[x0, y0, x1, y1]`` no quadrado unitário.

        Returns:
            dict: ``{"order": [int, ...]}`` (permutação dos índices).
        """
        return {"order": self.process_refine_reading_order(boxes)}

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
