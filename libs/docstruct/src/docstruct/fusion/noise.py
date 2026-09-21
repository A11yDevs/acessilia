"""Filtros de ruído para blocos de extração (porta de tree_differ_v2.py).

Cada filtro é uma função pura sobre listas de ``DiffBlock``. Stats de
decisão são acumulados em um dict fornecido pelo chamador (Contador).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Optional

from docstruct.fusion.similarity import (
    CJK_RE,
    PAGENUM_RE,
    WORD_RE,
    area,
    center,
    contain_frac,
    sim,
    swallows,
    union_box,
)
from docstruct.fusion.types import DiffBlock

DECOR_TYPES = {"page_header": "header", "page_footer": "footer"}
DECOR_ORDER = {"header": 0, "footer": 1, "page_number": 2}
TRAIL_NUM_RE = re.compile(
    r"^(?:(.*?[A-Za-z].*?)\s+(\d{1,4})|(\d{1,4})\s+(.*?[A-Za-z].*?))$"
)
MATH_RE = re.compile(
    r"\\(frac|sum|int|sqrt|lim|partial|infty|prod|left|right|leq|geq|neq|approx"
    r"|cdot|pm|alpha|beta|theta|pi|sigma|Delta)\b|[=<>]|\^\{?[a-zA-Z]"
)
LATEX_CMD_RE = re.compile(r"\\[A-Za-z]+\s*|[{}$^_]")


def quality(text: str) -> float:
    """Fração de tokens que parecem palavras/números reais (OCR lixo pontua baixo)."""
    toks = text.split()
    if not toks:
        return 0.0
    good = 0
    for t in toks:
        core = re.sub(r"[\W_]+", "", t)
        if WORD_RE.match(t) and (
            len(core) >= 2
            or core.isdigit()
            or core.lower() in ("a", "i", "o", "e", "y", "à", "é")
        ):
            good += 1
    return good / len(toks)


def lex_quality(text: str, lexicon: frozenset[str] | None) -> float:
    """Fração de tokens alfabéticos (len>=3) no léxico; 1.0 se não há tokens.
    Com léxico vazio, degrada para ``quality``."""
    if not lexicon:
        return quality(text)
    toks = [t for t in re.findall(r"[A-Za-z]+", text) if len(t) >= 3]
    if not toks:
        return 1.0
    return sum(t.lower() in lexicon for t in toks) / len(toks)


def is_junk(text: str) -> bool:
    """Resíduo de OCR de figura: sem palavras reais, quase só dígitos/símbolos,
    ou caractere repetido."""
    core = re.sub(r"\s+", "", text)
    if not core:
        return True
    if PAGENUM_RE.match(text):
        return False
    alnum = sum(c.isalnum() for c in core)
    if len(core) >= 8 and alnum / len(core) < 0.5:
        return True
    if len(set(core)) <= 2 and len(core) >= 4:
        return True
    if CJK_RE.search(core):
        return True
    return quality(text) < 0.34 and len(text.split()) >= 3


def latex_to_text(md: str) -> str:
    t = LATEX_CMD_RE.sub(" ", md)
    return re.sub(r"\s+", " ", t).strip()


def demote_formulas(blocks: list[DiffBlock], stats: Counter, tag: str) -> list[DiffBlock]:
    """Fórmulas sem operador matemático real (química, tabelas de treino) → texto."""
    for b in blocks:
        if b.kind != "formula":
            continue
        txt = latex_to_text(b.md)
        chem = (
            re.fullmatch(r"[A-Z0-9\s=\-+()\[\].,]+", txt.replace("\\equiv", "=")) is not None
        )
        if txt and (chem or not MATH_RE.search(b.md)):
            b.kind, b.md, b.text = "text", txt, txt
            stats[f"formula->text-{tag}"] += 1
    return blocks


def decor_role(b: DiffBlock, running: frozenset[str] = frozenset()) -> Optional[str]:
    if b.kind in ("table", "formula"):
        return None
    if PAGENUM_RE.match(b.md) and len(b.md) <= 16:
        return "page_number"
    role = DECOR_TYPES.get(b.type)
    if role is None and running and b.text in running and b.box is not None:
        cy = center(b.box)[1]
        role = "header" if cy < 0.5 else "footer"
    return role


def split_decor(
    blocks: list[DiffBlock],
    stats: Counter,
    tag: str,
    running: frozenset[str] = frozenset(),
    pagenum_cap: int = 0,
) -> tuple[list[DiffBlock], list[DiffBlock]]:
    """Separa body de decor (headers/footers/números de página)."""
    body: list[DiffBlock] = []
    decor: list[DiffBlock] = []
    demote: set[int] = set()
    if pagenum_cap:
        nums = [
            i
            for i, b in enumerate(blocks)
            if decor_role(b, running) == "page_number" and b.type not in DECOR_TYPES
        ]
        if len(nums) > pagenum_cap:
            for i in nums:
                bx = blocks[i].box
                cy = center(bx)[1] if bx else 0.5
                if 0.12 <= cy <= 0.88:
                    demote.add(i)
            stats[f"pagenum-{tag}-demoted"] += len(demote)
    for i, b in enumerate(blocks):
        role = None if i in demote else decor_role(b, running)
        if not role:
            body.append(b)
            continue
        if b.type not in DECOR_TYPES and role != "page_number":
            stats[f"decor-{tag}-running"] += 1
        m = TRAIL_NUM_RE.match(b.md) if role != "page_number" else None
        if m:
            txt, num = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
            decor.append(
                DiffBlock(
                    **{**b.as_dict(), "md": txt, "text": txt, "role": role}
                )
            )
            decor.append(
                DiffBlock(
                    **{**b.as_dict(), "md": num, "text": num, "role": "page_number"}
                )
            )
            stats[f"decor-{tag}-split-number"] += 1
        else:
            b.role = role
            decor.append(b)
        stats[f"decor-{tag}-{role}"] += 1
    return body, decor


def decor_tail(dec_d: list[DiffBlock], dec_m: list[DiffBlock]) -> list[str]:
    """Convenção do GT: header → footer → page_number após o body.
    Docling vence duplicatas."""
    seen = {d.text for d in dec_d}
    items = list(dec_d) + [m for m in dec_m if m.text not in seen]
    items.sort(key=lambda b: (DECOR_ORDER[b.role or "footer"], center(b.box)[1], center(b.box)[0]))
    return [b.md for b in items]


def suppress_in_regions(
    D: list[DiffBlock],
    M: list[DiffBlock],
    m_pics: list,
    stats: Counter,
    frac: float = 0.75,
    pic_min_blocks: int = 2,
    pic_max_quality: float = 0.7,
    pic_full_page: float = 0.9,
    mode: str = "both",
    pic_rule: str = "count-or-quality",
    table_full_page: float = 0.0,
    table_probe: bool = False,
    quality_fn: Callable[[str], float] = quality,
    lex_quality_fn: Callable[[str], float] = lambda t: quality(t),
) -> list[DiffBlock]:
    """Descarta blocos Docling dentro (>= frac) de tabela MinerU (as células
    já carregam o texto) ou dentro de figura MinerU com aparência de OCR de
    figura. Balões de gibi (poucos blocos legíveis) sobrevivem."""

    def captured(t: str, table_text: str) -> bool:
        n = len(t)
        if n < 8:
            return True
        probes = {t[:10], t[max(0, n // 2 - 5):n // 2 + 5], t[-10:]}
        return any(p and p in table_text for p in probes)

    tables = (
        [(m.box, m.text) for m in M if m.kind == "table" and m.box]
        if mode in ("both", "tables")
        else []
    )
    if table_full_page:
        big = [tb for tb, _ in tables if area(tb) >= table_full_page]
        if big:
            stats["table-full-page-skipped"] += len(big)
        tables = [(tb, tt) for tb, tt in tables if area(tb) < table_full_page]

    drop: set[int] = set()
    for i, d in enumerate(D):
        if d.kind not in ("text", "heading") or d.box is None:
            continue
        hit = [tt for tb, tt in tables if contain_frac(d.box, tb) >= frac]
        if not hit:
            continue
        if (
            table_probe
            and not any(captured(d.text, tt) for tt in hit)
            and min(quality_fn(d.md), lex_quality_fn(d.md)) >= 0.5
            and len([t for t in re.findall(r"[A-Za-z]+", d.md) if len(t) >= 3]) >= 2
        ):
            stats["keep-in-table-missing"] += 1
            continue
        drop.add(i)
        stats["suppress-in-table"] += 1
    if mode not in ("both", "pictures"):
        return [d for i, d in enumerate(D) if i not in drop]
    for pb in m_pics:
        inside = [
            i
            for i, d in enumerate(D)
            if i not in drop
            and d.kind in ("text", "heading")
            and d.box is not None
            and contain_frac(d.box, pb) >= frac
        ]
        if not inside:
            continue
        toks = sum(len(D[i].md.split()) for i in inside) or 1
        q = (
            sum(
                min(quality_fn(D[i].md), lex_quality_fn(D[i].md)) * len(D[i].md.split())
                for i in inside
            )
            / toks
        )
        full_page = area(pb) >= pic_full_page
        if pic_rule == "quality":
            hit = len(inside) >= pic_min_blocks and q < pic_max_quality
        else:
            hit = len(inside) >= pic_min_blocks or q < pic_max_quality
        if not full_page and hit:
            drop.update(inside)
            stats["suppress-in-picture"] += len(inside)
        elif full_page and q < 0.34:
            drop.update(inside)
            stats["suppress-in-picture-garbage"] += len(inside)
        else:
            stats["keep-in-picture"] += len(inside)
    return [d for i, d in enumerate(D) if i not in drop]


def group_split_blocks(
    A: list[DiffBlock],
    B: list[DiffBlock],
    stats: Counter,
    tag: str,
    frac: float = 0.6,
    min_sim: float = 0.0,
) -> list[DiffBlock]:
    """Funde blocos de texto de A geometricamente contidos (>= frac) num único
    bloco de texto de B (A sobre-segmentou o parágrafo que B manteve inteiro)."""
    owner: dict[int, int] = {}
    for i, a in enumerate(A):
        if a.kind != "text" or a.box is None:
            continue
        best, bf = None, 0.0
        for j, b in enumerate(B):
            if b.kind != "text" or b.box is None:
                continue
            f = contain_frac(a.box, b.box)
            if f > bf:
                best, bf = j, f
        if best is not None and bf >= frac:
            owner[i] = best
    groups: dict[int, list[int]] = {}
    for i, j in owner.items():
        groups.setdefault(j, []).append(i)
    merged_first: dict[int, DiffBlock] = {}
    absorbed: set[int] = set()
    for j, idxs in groups.items():
        if len(idxs) < 2:
            continue
        idxs.sort()
        parts = [A[i] for i in idxs]
        merged_text = "".join(p.text for p in parts)
        if sim(merged_text[:2000], B[j].text[:2000]) < min_sim:
            stats[f"merge-split-{tag}-rejected"] += 1
            continue
        merged_first[idxs[0]] = DiffBlock(
            md=" ".join(p.md for p in parts),
            kind="text",
            box=union_box(p.box for p in parts),
            text=merged_text,
            type=parts[0].type,
            merged=len(parts),
        )
        absorbed.update(idxs[1:])
        stats[f"merge-split-{tag}"] += 1
        stats[f"merge-split-{tag}-blocks"] += len(parts)
    out = []
    for i, a in enumerate(A):
        if i in absorbed:
            continue
        out.append(merged_first.get(i, a))
    return out


def fuse_line_runs(
    blocks: list[DiffBlock],
    stats: Counter,
    tag: str,
    short: int = 80,
    min_run: int = 3,
    max_len: int = 0,
    x_tol: float = 0.03,
    gap_mult: float = 1.3,
    h_ratio: float = 0.0,
) -> list[DiffBlock]:
    """Colunas de índice/referência: GT mantém 1 bloco por coluna, providers
    emitem 1 por linha. Funda sequências (>= min_run) de blocos curtos
    consecutivos alinhados à esquerda e verticalmente adjacentes."""
    def short_text(b: DiffBlock) -> bool:
        return (
            b.kind == "text"
            and b.box is not None
            and len(b.text) <= short
            and "\n" not in b.md
            and not b.md.lstrip().startswith("#")
        )

    def adjacent(p: DiffBlock, n: DiffBlock) -> bool:
        pb, nb = p.box, n.box
        hp, hn = max(pb[3] - pb[1], 1e-3), max(nb[3] - nb[1], 1e-3)
        h = max(hp, hn)
        gap = nb[1] - pb[3]
        return (
            abs(pb[0] - nb[0]) <= x_tol
            and -0.5 * h <= gap <= gap_mult * h
            and min(hp, hn) / h >= h_ratio
        )

    cand = [i for i, b in enumerate(blocks) if short_text(b)]
    cand.sort(key=lambda i: (blocks[i].box[0], blocks[i].box[1]))
    columns: list[list[int]] = []
    for i in cand:
        if columns and abs(blocks[columns[-1][0]].box[0] - blocks[i].box[0]) <= x_tol:
            columns[-1].append(i)
        else:
            columns.append([i])
    runs: list[list[int]] = []
    for col in columns:
        col.sort(key=lambda i: blocks[i].box[1])
        run = [col[0]]
        for i in col[1:]:
            if adjacent(blocks[run[-1]], blocks[i]):
                run.append(i)
            else:
                if len(run) >= min_run:
                    runs.append(run)
                run = [i]
        if len(run) >= min_run:
            runs.append(run)
    fused_at: dict[int, list[DiffBlock]] = {}
    absorbed: set[int] = set()
    for run in runs:
        chunk: list[int] = []
        chunks: list[list[int]] = []
        for i in run:
            if (
                chunk
                and max_len
                and sum(len(blocks[c].text) for c in chunk) + len(blocks[i].text) > max_len
            ):
                chunks.append(chunk)
                chunk = []
            chunk.append(i)
        chunks.append(chunk)
        for ch in chunks:
            if len(ch) == 1:
                continue
            parts = [blocks[i] for i in ch]
            fused_at.setdefault(min(ch), []).append(
                DiffBlock(
                    md=" ".join(p.md for p in parts),
                    kind="text",
                    box=union_box(p.box for p in parts),
                    text="".join(p.text for p in parts),
                    type=parts[0].type,
                    fused=len(parts),
                )
            )
            absorbed.update(ch)
            stats[f"fuse-lines-{tag}"] += 1
            stats[f"fuse-lines-{tag}-blocks"] += len(ch)
    out: list[DiffBlock] = []
    for i, b in enumerate(blocks):
        if i in fused_at:
            out.extend(fused_at[i])
        elif i not in absorbed:
            out.append(b)
    return out
