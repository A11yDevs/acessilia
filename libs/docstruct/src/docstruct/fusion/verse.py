"""Chunking de verso / drama / listas de registros.

Porta de ``verse_blocks`` e auxiliares do Tree Differ v2 (PR #125, Dr.DocBench).

Motivação: o avaliador do Dr.DocBench só consegue reagrupar predições
consecutivas em um bloco do ground truth quando as strings têm <= 300 chars
(``_FUZZY_MAX_LEN``). Um bloco de verso de página inteira perde todas as
estrofes menos uma. Fontes VLM (MinerU hybrid) preservam as quebras de linha do
verso, então este módulo as divide em pedaços <= ``max_chars``, preferindo fins
de estrofe (linha em branco, pontuação final de frase, próximo rótulo de
falante).

O ground truth mantém um bloco por estrofe/fala e os números de linha marginais
como blocos separados. Listas de registros (TOC, índice, resultados) também são
mantidas uma entrada por bloco pelo GT — daí ``record_like`` distinguir
"registro" de "verso real": linhas de verso terminam em palavras e o GT mantém
a estrofe inteira (frequentemente > 300 chars), então essas devem ficar
inteiras.

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from docstruct.fusion.types import DiffBlock
from docstruct.text.normalize import norm
from docstruct.types import BBox

SPEAKER_RE = re.compile(r"^(?:[A-Z][A-Z'’.\-]*(?: [A-Z][A-Z'’.\-]*){0,3})[.:]?$")
SENT_END_RE = re.compile(r"[.!?…][”\"’')\]]*$")
RECORD_END_RE = re.compile(r"\d\W*$")
LEADER_RE = re.compile(r"\.{3,}|…|\\dotfill")

# Prefixos de markdown que indicam estrutura, não verso.
_STRUCTURE_PREFIXES = ("#", "<", "|", "$$", "![")

# Comprimento máximo de um rótulo de falante isolado (ex.: "HAMLET:").
_MAX_SPEAKER_LABEL = 32


def record_like(lines: list[str], min_frac: float = 0.6) -> bool:
    """True se ``lines`` parece TOC / índice / lista de resultados.

    A maioria das linhas termina em número (``min_frac``) ou carrega dot leaders
    (>= 0.5). Linhas de verso/diálogo reais terminam em palavras.
    """
    ls = [l.strip() for l in lines if l.strip()]
    if not ls:
        return False
    endnum = sum(bool(RECORD_END_RE.search(l)) for l in ls) / len(ls)
    leaders = sum(bool(LEADER_RE.search(l)) for l in ls) / len(ls)
    return endnum >= min_frac or leaders >= 0.5


def verse_lines(
    md: str,
    min_lines: int = 3,
    max_median: int = 70,
    max_line: int = 120,
) -> Optional[list[str]]:
    """Linhas de um bloco com cara de verso, ou ``None``.

    Exige várias linhas curtas separadas por newline simples e recusa blocos que
    começam com estrutura de markdown (heading, HTML, tabela, fórmula, imagem).
    """
    s = md.strip()
    if "\n" not in s or s.startswith(_STRUCTURE_PREFIXES):
        return None
    lines = [l.rstrip() for l in s.split("\n")]
    nonempty = [l for l in lines if l.strip()]
    if len(nonempty) < min_lines:
        return None
    lens = sorted(len(l) for l in nonempty)
    if lens[len(lens) // 2] > max_median or lens[-1] > max_line:
        return None
    return lines


def chunk_verse(lines: list[str], max_chars: int, soft: float = 0.6) -> list[str]:
    """Divide ``lines`` em pedaços <= ``max_chars``, preferindo fins de estrofe.

    Corta em linha em branco (estrofe), antes de um rótulo de falante isolado e
    após pontuação final de frase quando o pedaço já passou de ``soft`` do
    limite. O comprimento é medido sobre o texto normalizado.
    """
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        if cur:
            chunks.append("\n".join(cur))
        cur, cur_len = [], 0

    for l in lines:
        s = l.strip()
        if not s:  # linha em branco = quebra de estrofe
            flush()
            continue
        if cur and SPEAKER_RE.match(s) and len(s) <= _MAX_SPEAKER_LABEL:
            flush()
        n = len(norm(s))
        if cur and cur_len + n > max_chars:
            flush()
        cur.append(s)
        cur_len += n
        if cur_len >= soft * max_chars and SENT_END_RE.search(s):
            flush()
    flush()
    return chunks


def split_box_rows(box: Optional[BBox], parts: list[int]) -> list[Optional[BBox]]:
    """Divide ``box`` verticalmente em proporção ao número de linhas de cada parte."""
    if box is None:
        return [None] * len(parts)
    tot = sum(parts) or 1
    y0, h = box[1], box[3] - box[1]
    out: list[Optional[BBox]] = []
    acc = 0
    for p in parts:
        out.append((box[0], y0 + h * acc / tot, box[2], y0 + h * (acc + p) / tot))
        acc += p
    return out


def verse_blocks(
    blocks: list[DiffBlock],
    stats: Counter,
    tag: str,
    max_chars: int,
    kind: str = "records",
) -> list[DiffBlock]:
    """Divide blocos de verso/registro em pedaços, marcando-os com ``verse=True``.

    ``kind="records"`` só divide o que passa em ``record_like`` (preserva verso
    real inteiro); ``kind="all"`` divide todo bloco com cara de verso. Blocos não
    textuais e blocos que resultariam em um único pedaço são devolvidos como
    estão. ``stats`` recebe contadores ``verse-{tag}-{whole,kept,split,chunks}``.
    """
    out: list[DiffBlock] = []
    for b in blocks:
        lines = verse_lines(b.md) if b.kind == "text" else None
        if lines is None:
            out.append(b)
            continue
        if kind == "records" and not record_like(lines):
            out.append(b)
            stats[f"verse-{tag}-whole"] += 1
            continue
        chunks = chunk_verse(lines, max_chars)
        if len(chunks) <= 1:
            out.append(b)
            stats[f"verse-{tag}-kept"] += 1
            continue
        boxes = split_box_rows(b.box, [c.count("\n") + 1 for c in chunks])
        for c, bx in zip(chunks, boxes):
            out.append(
                DiffBlock(
                    md=c,
                    kind=b.kind,
                    box=bx,
                    text=norm(c),
                    type=b.type,
                    role=b.role,
                    merged=b.merged,
                    fused=b.fused,
                    verse=True,
                )
            )
        stats[f"verse-{tag}-split"] += 1
        stats[f"verse-{tag}-chunks"] += len(chunks)
    return out
