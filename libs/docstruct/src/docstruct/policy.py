"""Políticas de fusão multi-provider.

Os defaults são conservadores/neutros. Os conjuntos de flags calibrados
contra o benchmark Dr.DocBench (PR #98, variantes v3..v13) ficam como
presets nomeados — nunca como default — porque foram sobreajustados ao
split dev (gap dev→test ≈ −6).
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal


@dataclass(frozen=True)
class FusionPolicy:
    """Configuração imutável da fusão e dos filtros de ruído.

    Agrupada por preocupação: alinhamento, escolha de texto, reconstrução,
    ruído, fórmulas e rotação.
    """

    # --- Alinhamento (núcleo do Tree Differ) ---
    align_lambda: float = 0.5  # peso texto vs bbox na similaridade
    align_tau: float = 0.6  # limiar de pareamento Húngaro

    # --- Escolha de texto por bloco ---
    text_pick: Literal["auto", "docling", "mineru"] = "auto"
    pick_guard: bool = True  # proteção contra Docling engolir colunas

    # --- Reconstrução de parágrafos/colunas ---
    merge_paragraphs: bool = True
    fuse_lines: bool = False
    fuse_h_ratio: float = 0.8

    # --- Ruído ---
    decor_tail: bool = True  # header/footer movidos ao fim da página
    running_heads: bool = True
    pagenum_cap: bool = True
    junk_filter: bool = True
    suppress_regions: bool = True  # texto Docling dentro de tabela/figura MinerU
    pic_need_text: bool = True  # exceto quando o provider não leu texto na página

    # --- Fórmulas ---
    formula_text: bool = True  # fórmulas sem operador matemático → texto
    inline_math_promote: bool = True  # parágrafo inteiro com math → display

    # --- Rotação ---
    orientation_min_confidence: float = 0.85
    orientation_reinfer: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.align_lambda <= 1.0:
            raise ValueError(f"align_lambda deve estar em [0,1], got {self.align_lambda}")
        if not 0.0 < self.align_tau <= 1.0:
            raise ValueError(f"align_tau deve estar em (0,1], got {self.align_tau}")
        if self.fuse_lines and not self.merge_paragraphs:
            raise ValueError("fuse_lines sem merge_paragraphs é no-op: combinação inválida")

    def to_dict(self) -> dict[str, Any]:
        """Serialização para logs/config/tools Agno."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FusionPolicy":
        """Constrói a partir de dict, ignorando chaves desconhecidas."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def drbench_v12(cls) -> "FusionPolicy":
        """Preset do differ-v12 (calibrado no dev do Dr.DocBench — NÃO usar
        como default de produção)."""
        return cls(
            align_lambda=0.5,
            align_tau=0.6,
            text_pick="auto",
            pick_guard=True,
            merge_paragraphs=True,
            fuse_lines=True,
            fuse_h_ratio=0.8,
            decor_tail=True,
            running_heads=True,
            pagenum_cap=True,
            junk_filter=True,
            suppress_regions=True,
            pic_need_text=False,
            formula_text=False,
            inline_math_promote=True,
        )

    @classmethod
    def drbench_v13(cls) -> "FusionPolicy":
        """Preset do differ-v13 (pic-need-text + formula-text ativados)."""
        return cls(
            **{**cls.drbench_v12().to_dict(), "pic_need_text": True, "formula_text": True}
        )
