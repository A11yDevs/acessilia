"""Junção dos blocos curtos finais (cabeçalho/rodapé/número de página).

Porta de ``tailjoin.py`` e ``tailjoin3.py`` do Dr.DocBench (PR #125).

O ground truth renderiza o cabeçalho corrente / rodapé / número de página no
fim da página, mas a ordem mútua entre eles é dependente do anotador. Juntá-los
em um único bloco evita que essa ordem custe RO.

``tailjoin3`` condiciona a junção à posição do número de página: o GT mantém o
cabeçalho corrente antes de um número no **rodapé** em 91% das páginas de dev,
mas fica ~70/30 quando o número está no **topo**. Então a cauda só é juntada
quando o número não é sabidamente de rodapé; no rodapé, ``bot="keep"`` deixa a
cauda como está e ``bot="hdr"`` move os números para o fim.

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import re
from typing import Optional

from docstruct.fusion.types import DiffBlock

# Número de página: arábico ou romano, até 5 caracteres.
PAGE_NUMBER_RE = re.compile(r"[\divxlcIVXLC]{1,5}")

# Modos de junção da cauda.
MODES = ("num", "end", "any")

# Comportamento quando o número de página está no rodapé.
BOT_MODES = ("keep", "hdr")


def is_page_number(text: str) -> bool:
    """True se ``text`` é um número de página isolado (arábico ou romano)."""
    return PAGE_NUMBER_RE.fullmatch(text.strip()) is not None


def is_short_block(text: str, max_len: int) -> bool:
    """True se ``text`` é curto e de linha única (candidato a cauda)."""
    s = text.strip()
    return len(s) <= max_len and "\n" not in s


def tail_start(blocks: list[str], max_len: int, k: int) -> int:
    """Índice onde começa a cauda de blocos curtos finais.

    Anda para trás a partir do fim enquanto os blocos forem curtos, parando
    depois de ``k`` blocos ou ao chegar ao primeiro bloco.
    """
    j = len(blocks)
    while j > 1 and len(blocks) - j < k and is_short_block(blocks[j - 1], max_len):
        j -= 1
    return j


def join_tail(blocks: list[str], mode: str, max_len: int, k: int) -> list[str]:
    """Junta a cauda de blocos curtos finais em um único bloco.

    ``mode="num"`` exige que algum bloco da cauda seja um número de página;
    ``mode="end"`` exige que o primeiro ou o último seja; ``mode="any"`` não
    exige nada. Devolve uma nova lista; a entrada não é modificada.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    j = tail_start(blocks, max_len, k)
    tail = blocks[j:]
    if len(tail) < 2 or j < 1:
        return list(blocks)
    ok = (
        mode == "any"
        or (mode == "num" and any(is_page_number(b) for b in tail))
        or (mode == "end" and (is_page_number(tail[0]) or is_page_number(tail[-1])))
    )
    if not ok:
        return list(blocks)
    return blocks[:j] + [" ".join(b.strip() for b in tail)]


def page_number_position(blocks: list[DiffBlock]) -> Optional[str]:
    """Posição vertical do número de página: ``"top"``, ``"bot"`` ou ``None``.

    Usa o centro vertical do bbox normalizado (``< 0.5`` = topo). Blocos sem
    bbox ou sem número de página são ignorados.
    """
    for b in blocks:
        if b.role in ("header", "footer", "page_number") and is_page_number(b.md):
            if b.box is None:
                continue
            cy = (b.box[1] + b.box[3]) / 2
            return "top" if cy < 0.5 else "bot"
    return None


def tailjoin3(
    blocks: list[str],
    position: Optional[str],
    max_len: int,
    k: int,
    bot: str = "keep",
) -> list[str]:
    """Regra ``tj3``: junta a cauda condicionada à posição do número de página.

    Quando ``position == "bot"``, ``bot="keep"`` deixa a cauda intacta e
    ``bot="hdr"`` reordena a cauda movendo os números de página para o fim.
    Caso contrário, junta a cauda no modo ``"end"``.
    """
    if bot not in BOT_MODES:
        raise ValueError(f"bot must be one of {BOT_MODES}, got {bot!r}")
    j = tail_start(blocks, max_len, k)
    tail = blocks[j:]
    if len(tail) < 2 or j < 1:
        return list(blocks)
    if not (is_page_number(tail[0]) or is_page_number(tail[-1])):
        return list(blocks)
    if position == "bot":
        if bot == "hdr":
            return (
                blocks[:j]
                + [b for b in tail if not is_page_number(b)]
                + [b for b in tail if is_page_number(b)]
            )
        return list(blocks)
    return blocks[:j] + [" ".join(b.strip() for b in tail)]
