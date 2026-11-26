"""Contratos fundamentais da lib docstruct.

Todos os tipos aqui são leves e puros: dataclasses sem I/O, sem rede,
sem dependência do backend. O backend importa destes tipos; nunca o contrário.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Coordenadas em espaço de página (origem no canto superior esquerdo).
# Convenção igual ao PyMuPDF/Docling: (x0, y0, x1, y1).
BBox = tuple[float, float, float, float]

# The two id injection hooks share the parameter name ``id_factory`` but not
# the arity, so each module declares a distinct alias: a document has a single
# id, while a block id comes from the block's 1-based index.
DocumentIdFactory = Callable[[], str]
BlockIdFactory = Callable[[int], str]


@dataclass
class CanonicalBlock:
    """Bloco canônico: unidade mínima de conteúdo estruturado.

    ``bbox`` e ``page_index`` são opcionais: provedores sem geometria
    (ex.: texto puro) produzem ``None`` e a lib degrada graciosamente
    (heurísticas de fusão que dependem de bbox ficam desativadas).
    """

    id: str
    type: str
    text: str
    bbox: BBox | None = None
    page_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalDocument:
    """Deprecated since 0.5.3: legacy document dataclass kept for compatibility.

    New code should use the dictionaries returned by
    ``docstruct.canonical.build_canonical_document``, whose structure is defined
    by ``docstruct.schemas.accessible_document_schema``. This dataclass is not
    the serialized canonical schema. Construction and ``blocks()`` are unchanged.
    """

    __deprecated__ = (
        "CanonicalDocument is deprecated since docstruct 0.5.3. Use dictionaries "
        "from docstruct.canonical.build_canonical_document and the schema from "
        "docstruct.schemas.accessible_document_schema."
    )

    title: str | None
    sections: list["CanonicalSection"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def blocks(self) -> list[CanonicalBlock]:
        """Todos os blocos do documento, em ordem de leitura."""
        return [b for s in self.sections for b in s.blocks]


@dataclass
class CanonicalSection:
    """Deprecated since 0.5.3: legacy section dataclass kept for compatibility.

    Use the section dictionaries returned by
    ``docstruct.canonical.build_canonical_document`` and described by
    ``docstruct.schemas.accessible_document_schema``. Fields and defaults stay
    unchanged; the serialized schema's child sections belong to dictionaries.
    """

    __deprecated__ = (
        "CanonicalSection is deprecated since docstruct 0.5.3. Use section "
        "dictionaries from docstruct.canonical.build_canonical_document and the "
        "schema from docstruct.schemas.accessible_document_schema."
    )

    id: str
    level: int
    title: str | None
    blocks: list[CanonicalBlock] = field(default_factory=list)


@dataclass
class Region:
    """Região de página classificada (espelho do backend, sem importar fitz).

    ``image_bytes`` permanece aqui para compatibilidade com o fluxo atual,
    mas a lib não o lê nem o processa — só transporta.
    """

    bbox: BBox
    type: str
    text: str
    image_bytes: bytes | None
    confidence: float
    page_num: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BlockPairing:
    """Resultado do alinhamento entre dois conjuntos de blocos."""

    a: CanonicalBlock | None  # None = só existe em b (inserção)
    b: CanonicalBlock | None  # None = só existe em a (remoção)
    similarity: float = 0.0

    @property
    def is_match(self) -> bool:
        return self.a is not None and self.b is not None


@dataclass
class OrientationResult:
    """Detecção de orientação de uma página (produzida por serviço externo)."""

    page_index: int
    rotation: int  # 0, 90, 180, 270 — ângulo para corrigir
    confidence: float

    @property
    def needs_correction(self) -> bool:
        return self.rotation != 0
