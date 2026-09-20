"""Tipos internos do fusor (não fazem parte da API pública estável)."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Optional

from docstruct.types import BBox


@dataclass
class DiffBlock:
    """Bloco interno do fusor: equivalente a um bloco de provider já
    classificado, com bbox normalizado ao quadrado unitário."""

    md: str
    kind: str  # "text" | "heading" | "table" | "formula"
    box: Optional[BBox]
    text: str
    type: str  # tipo original do provider
    role: Optional[str] = None  # decor: "header" | "footer" | "page_number"
    merged: int = 0
    fused: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def copy(self) -> "DiffBlock":
        return DiffBlock(**self.as_dict())


@dataclass
class ProviderBlocks:
    """Blocos de um provider para uma página, já com bboxes normalizados."""

    blocks: list[DiffBlock] = field(default_factory=list)
    pictures: list[BBox] = field(default_factory=list)  # bboxes de imagens
