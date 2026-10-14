"""Guarda contra "inundação" de blocos curtos por um provider.

Porta de ``flood_guard`` do Tree Differ v2 (PR #125, Dr.DocBench).

Em páginas de gráfico/diagrama o Docling emite cada marca de eixo e cada rótulo
como um bloco (dezenas), enquanto o MinerU vê apenas as poucas legendas. Quando
o Docling inunda o MinerU, os blocos de texto curtos sem nenhuma palavra de
léxico são descartados.

O léxico é injetado pelo chamador (mesmo padrão de ``noise.lex_quality``), para
que a biblioteca continue sem dependências pesadas e sem I/O.
"""
from __future__ import annotations

import re
from collections import Counter

from docstruct.fusion.types import DiffBlock

_WORD_RE = re.compile(r"[A-Za-z]{3,}")

# Só dispara em páginas densas: mínimo de blocos textuais do provider A.
DEFAULT_MIN_BLOCKS = 30

# Comprimento máximo (em chars normalizados) de um bloco candidato a descarte.
DEFAULT_SHORT = 15


def flood_guard(
    a: list[DiffBlock],
    b: list[DiffBlock],
    stats: Counter,
    ratio: float,
    lexicon: frozenset[str] | None = None,
    tag: str = "docling",
    min_blocks: int = DEFAULT_MIN_BLOCKS,
    short: int = DEFAULT_SHORT,
) -> list[DiffBlock]:
    """Descarta blocos curtos de ``a`` quando ``a`` inunda ``b``.

    ``a`` é o provider suspeito de inundar (Docling) e ``b`` o de referência
    (MinerU). Só age quando ``a`` tem >= ``min_blocks`` blocos textuais e pelo
    menos ``ratio`` vezes os de ``b``. Nesse caso remove os blocos de texto com
    ``len(text) <= short`` que não contenham nenhuma palavra do ``lexicon``.

    ``stats`` recebe ``flood-{tag}-dropped`` e ``flood-pages``.
    """
    na = sum(x.kind in ("text", "heading") for x in a)
    nb = sum(x.kind in ("text", "heading") for x in b)
    if na < min_blocks or na < ratio * max(nb, 1):
        return a
    lex = lexicon or frozenset()
    keep: list[DiffBlock] = []
    for x in a:
        if (
            x.kind == "text"
            and len(x.text) <= short
            and not any(w.lower() in lex for w in _WORD_RE.findall(x.md))
        ):
            stats[f"flood-{tag}-dropped"] += 1
        else:
            keep.append(x)
    if len(keep) < len(a):
        stats["flood-pages"] += 1
    return keep
