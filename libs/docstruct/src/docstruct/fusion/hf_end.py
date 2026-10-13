"""Convenção do GT: cabeçalho corrente / rodapé / número de página vêm por último.

Porta de ``hfmove.py`` e do ``--hf-end`` de ``dots_page_ocr.py`` /
``dsocr_page_ocr.py`` do Dr.DocBench (PR #125).

O ground truth renderiza o cabeçalho corrente, o rodapé e o número de página no
**fim** da página. Duas operações:

- ``move_hf_to_end`` — reordena elementos rotulados como header/footer para o
  fim (a convenção do ``--hf-end``). dots.ocr RO 61.6 → 80.2.
- ``move_body_hf_to_tail`` — move para a cauda blocos curtos que estão no corpo
  mas cujo texto coincide (normalizado) com um elemento de header/footer de
  ambos os layouts (``hfmove.py``).

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import re

# Categorias de layout que representam cabeçalho/rodapé.
HF_CATEGORIES = ("Page-header", "Page-footer")

# Tipos de bloco do TeleOCR que representam cabeçalho/rodapé/número.
HF_TYPES = ("header", "footer", "page_number")

# Comprimento máximo de um bloco do corpo candidato a ser movido.
MAX_BODY_HF_LEN = 80

_NON_WORD_RE = re.compile(r"[\W_]+")


def hf_norm(s: str | None) -> str:
    """Normaliza o texto de um bloco de cabeçalho/rodapé para comparação."""
    return _NON_WORD_RE.sub("", (s or "").lower())


def move_hf_to_end(els: list[dict], categories: tuple[str, ...] = HF_CATEGORIES) -> list[dict]:
    """Reordena ``els`` movendo os elementos de cabeçalho/rodapé para o fim.

    Preserva a ordem relativa dentro de cada grupo. Devolve uma nova lista.
    """
    hf = set(categories)
    return [e for e in els if e.get("category") not in hf] + [
        e for e in els if e.get("category") in hf
    ]


def hf_texts(blocks: list[dict], types: tuple[str, ...] = HF_TYPES) -> set[str]:
    """Textos normalizados dos blocos de cabeçalho/rodapé/número de página."""
    return {
        hf_norm(b.get("text"))
        for b in blocks
        if b.get("type") in types
    } - {""}


def hf_categories_texts(els: list[dict], categories: tuple[str, ...] = HF_CATEGORIES) -> set[str]:
    """Textos normalizados dos elementos de layout de cabeçalho/rodapé."""
    return {
        hf_norm(e.get("text"))
        for e in els
        if e.get("category") in categories
    } - {""}


def move_body_hf_to_tail(
    blocks: list[str],
    tele_texts: set[str],
    dots_texts: set[str],
    need: str = "both",
    max_len: int = MAX_BODY_HF_LEN,
) -> list[str]:
    """Move para a cauda os blocos de cabeçalho/rodapé que estão no corpo.

    Um bloco é movido quando é curto (``<= max_len``) e seu texto normalizado
    (sem marcação de heading) está em ``tele_texts`` e/ou ``dots_texts``
    conforme ``need``: ``"both"`` exige os dois, ``"one"`` exige um.

    A cauda já existente (run final de blocos de cabeçalho/rodapé) é deixada
    como está; só os blocos encontrados antes dela são movidos. Devolve uma nova
    lista.
    """
    if need not in ("both", "one"):
        raise ValueError(f"need must be 'both' or 'one', got {need!r}")
    hf = (tele_texts & dots_texts) if need == "both" else (tele_texts | dots_texts)
    j = len(blocks)
    while j > 0 and hf_norm(blocks[j - 1].lstrip("# ")) in hf:
        j -= 1
    mv = [i for i in range(j) if len(blocks[i]) <= max_len and hf_norm(blocks[i].lstrip("# ")) in hf]
    if mv and len(blocks) > len(mv):
        return [b for i, b in enumerate(blocks) if i not in mv] + [blocks[i] for i in mv]
    return list(blocks)
