"""Números de linha marginais de verso.

Porta de ``line_number_chain`` e ``extract_line_numbers`` do Tree Differ v2
(PR #125, Dr.DocBench).

O ground truth mantém os números de linha marginais como blocos próprios. Os
OCR às vezes os embutem no meio do texto ("be seen 3964 or recognized") ou os
deixam como linhas soltas. Este módulo detecta a progressão aritmética típica
de numeração de verso (passo 5, 4, 10, 2 ou 3), remove esses números do texto e
os emite como blocos separados logo após o bloco de origem.

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import re
from collections import Counter

from docstruct.fusion.types import DiffBlock
from docstruct.text.normalize import norm
from docstruct.types import BBox

STANDALONE_INT_RE = re.compile(r"(?<![\w.,/:\-])(\d{1,4})(?![\w.,/:%\-])")

# Passos típicos de numeração de linha de verso.
DEFAULT_STEPS = (5, 4, 10, 2, 3)

# Só vale a pena procurar números em blocos com texto suficiente.
_MIN_TEXT_LEN = 120

# Largura da faixa marginal onde os números são reposicionados.
_MARGIN_WIDTH = 0.06


def line_number_chain(
    values: list[int],
    steps: tuple[int, ...] = DEFAULT_STEPS,
    min_len: int = 3,
) -> tuple[int, set[int]]:
    """Índices da maior sequência de ``values`` em progressão aritmética.

    Devolve ``(passo, índices)``. Os valores não precisam ser adjacentes na
    lista (anos e figuras podem se intercalar). Devolve ``(0, set())`` quando
    nenhuma sequência atinge ``min_len``.
    """
    best: tuple[int, set[int]] = (0, set())
    for step in steps:
        for i in range(len(values)):
            chain = [i]
            for j in range(i + 1, len(values)):
                if values[j] == values[chain[-1]] + step:
                    chain.append(j)
            if len(chain) >= min_len and len(chain) > len(best[1]):
                best = (step, set(chain))
    return best


def extract_line_numbers(
    blocks: list[DiffBlock],
    stats: Counter,
    tag: str,
) -> list[DiffBlock]:
    """Move números de linha marginais para blocos próprios.

    Para cada bloco de texto longo, detecta os inteiros isolados que formam uma
    progressão de numeração de verso, remove-os do markdown e emite um bloco
    ``type="line_number"`` por número, logo após o bloco de origem (que recebe
    ``verse_nums=True``). Blocos que já passaram por isso, blocos não textuais e
    blocos que ficariam vazios são devolvidos como estão.

    ``stats`` recebe ``line-numbers-{tag}`` (blocos alterados) e
    ``line-numbers-{tag}-count`` (números extraídos).
    """
    out: list[DiffBlock] = []
    for b in blocks:
        if b.kind != "text" or b.verse_nums or len(b.text) < _MIN_TEXT_LEN:
            out.append(b)
            continue
        hits = list(STANDALONE_INT_RE.finditer(b.md))
        if len(hits) < 3:
            out.append(b)
            continue
        _, idx = line_number_chain([int(h.group(1)) for h in hits])
        if not idx:
            out.append(b)
            continue
        md = b.md
        nums: list[str] = []
        for k in sorted(idx, reverse=True):
            h = hits[k]
            nums.append(h.group(1))
            md = md[: h.start()] + md[h.end() :]
        md = re.sub(r"[ \t]{2,}", " ", md)
        md = "\n".join(l.rstrip() for l in md.split("\n") if l.strip())
        nums.reverse()
        if not norm(md):
            out.append(b)
            continue
        out.append(
            DiffBlock(
                md=md,
                kind=b.kind,
                box=b.box,
                text=norm(md),
                type=b.type,
                role=b.role,
                merged=b.merged,
                fused=b.fused,
                verse=b.verse,
                verse_nums=True,
            )
        )
        bx = b.box
        for n in nums:
            nbox: BBox | None = (
                (max(0.0, bx[2] - _MARGIN_WIDTH), bx[1], bx[2], bx[3]) if bx else None
            )
            out.append(
                DiffBlock(md=n, kind="text", box=nbox, text=norm(n), type="line_number")
            )
        stats[f"line-numbers-{tag}"] += 1
        stats[f"line-numbers-{tag}-count"] += len(nums)
    return out
