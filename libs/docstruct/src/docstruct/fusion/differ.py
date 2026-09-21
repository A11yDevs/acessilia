"""Tree Differ — fusão block-level de dois providers (porta de merge_v2).

Matching: atribuição bipartida (Húngaro) entre blocos A e B com
cost = (1-lambda)*(1-sim_txt) + lambda*(1-IoU); pares com cost > tau ficam
sem par. Esqueleto de leitura: ordem do provider B (MinerU), com blocos
unilaterais de A (Docling) inseridos junto ao vizinho geometricamente
mais próximo.

Porta fiel do tree_differ_v2.py da PR #98, com:
- scipy → _hungarian puro;
- CLI flags → FusionPolicy;
- stats acumulados em Counter retornado ao chamador.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from docstruct.fusion._hungarian import linear_sum_assignment
from docstruct.fusion.noise import (
    DECOR_TYPES,
    decor_tail,
    demote_formulas,
    fuse_line_runs,
    group_split_blocks,
    is_junk,
    quality,
    split_decor,
    suppress_in_regions,
)
from docstruct.fusion.similarity import center, contain_frac, iou, sim, swallows
from docstruct.fusion.types import DiffBlock
from docstruct.policy import FusionPolicy


def _pick_text(
    d: DiffBlock, m: DiffBlock, M_texts: list[DiffBlock],
    policy: FusionPolicy, stats: Counter,
) -> str:
    if policy.text_pick == "docling":
        stats["pair-text->docling"] += 1
        return d.md
    if policy.text_pick == "mineru":
        stats["pair-text->mineru"] += 1
        return m.md
    # auto: MinerU vence no corpo, a menos que tenha truncado ou OCR pior
    ld, lm = len(d.text), len(m.text)
    if lm < 0.6 * ld:
        if policy.pick_guard and ld > policy.pick_guard * lm and swallows(
            d.text, [o.text for o in M_texts if o is not m and o.kind == "text"]
        ):
            stats["pair-text-auto->mineru(docling-swallowed)"] += 1
            return m.md
        stats["pair-text-auto->docling(longer)"] += 1
        return d.md
    if ld < 0.6 * lm:
        stats["pair-text-auto->mineru(longer)"] += 1
        return m.md
    qd, qm = quality(d.md), quality(m.md)
    if qd > qm + 0.05:
        stats["pair-text-auto->docling(quality)"] += 1
        return d.md
    stats["pair-text-auto->mineru"] += 1
    return m.md


def _pick(
    d: DiffBlock, m: DiffBlock, M: list[DiffBlock],
    policy: FusionPolicy, stats: Counter,
) -> str:
    if d.kind == "table" or m.kind == "table":
        if d.kind != m.kind:
            stats["pair-only-one-table"] += 1
            return d.md if d.kind == "table" else m.md
        stats["pair-table->docling"] += 1
        return d.md
    if d.kind == "formula" or m.kind == "formula":
        if d.kind != m.kind:
            stats["pair-only-one-formula"] += 1
            return d.md if d.kind == "formula" else m.md
        stats["pair-formula->docling"] += 1
        return d.md
    if d.kind == "heading" or m.kind == "heading":
        stats["pair-heading->docling"] += 1
        return d.md if d.kind == "heading" else m.md
    return _pick_text(d, m, M, policy, stats)


def merge_blocks(
    D: list[DiffBlock],
    M: list[DiffBlock],
    policy: FusionPolicy,
    *,
    min_len: int = 20,
    garbage_frac: float = 0.0,
    m_pics: list | None = None,
    running: frozenset[str] = frozenset(),
    decor_wins: bool = False,
    stats: Counter | None = None,
) -> tuple[list[str], Counter]:
    """Funde os blocos dos dois providers. Retorna (markdowns ordenados, stats).

    Args:
        D: blocos do provider A (Docling).
        M: blocos do provider B (MinerU) — esqueleto de ordem de leitura.
        policy: FusionPolicy com as alavancas.
        min_len: tamanho mínimo para manter bloco Docling unilateral.
        garbage_frac: fallback para ordem Docling quando quase nada casa.
        m_pics: bboxes de figuras do provider B (para suppress).
        running: textos de running heads do documento (pré-computados).
        decor_wins: body repetindo header/footer é descartado.
        stats: Counter opcional para acumular decisões.
    """
    stats = stats if stats is not None else Counter()
    tail: list[str] = []

    if policy.formula_text:
        D = demote_formulas(D, stats, "docling")
        M = demote_formulas(M, stats, "mineru")
    if policy.suppress_regions:
        mode = "both"
        if policy.pic_need_text and sum(
            m.kind in ("text", "heading") for m in M
        ) <= 1:
            stats["pic-suppress-skipped(mineru-no-text)"] += 1
            mode = "tables"
        D = suppress_in_regions(
            D, M, m_pics or [], stats, mode=mode,
        )
    if policy.decor_tail:
        D, dec_d = split_decor(D, stats, "docling", running, 0)
        M, dec_m = split_decor(M, stats, "mineru", running, 0)
        body_txt = {b.text for b in D + M if b.text}
        kept = []
        for b in dec_d + dec_m:
            if b.role != "page_number" and b.text in body_txt and not decor_wins:
                stats["decor-dup-of-body"] += 1
            else:
                kept.append(b)
        if decor_wins:
            dec_txt = {b.text for b in kept if b.role != "page_number" and b.text}
            nD, nM = len(D), len(M)
            D = [
                b for b in D
                if not (b.kind in ("text", "heading") and b.text in dec_txt)
            ]
            M = [
                b for b in M
                if not (b.kind in ("text", "heading") and b.text in dec_txt)
            ]
            stats["body-dup-of-decor"] += (nD - len(D)) + (nM - len(M))
        dec_d = [b for b in kept if b in dec_d]
        dec_m = [b for b in kept if b in dec_m]
        tail = decor_tail(dec_d, dec_m)
    if policy.junk_filter:
        D = [d for d in D if not (d.kind == "text" and is_junk(d.md))] or D
        if len(D) == 0:
            stats["junk-docling"] += 1
        M = [m for m in M if not (m.kind == "text" and is_junk(m.md))] or M
        if len(M) == 0:
            stats["junk-mineru"] += 1
    if policy.fuse_lines:
        D = fuse_line_runs(D, stats, "docling", h_ratio=policy.fuse_h_ratio)
        M = fuse_line_runs(M, stats, "mineru", h_ratio=policy.fuse_h_ratio)
    if policy.merge_paragraphs:
        D = group_split_blocks(D, M, stats, "docling")
        M = group_split_blocks(M, D, stats, "mineru")

    if not M:
        stats["mineru_empty->docling"] += 1
        return [d.md for d in D] + tail, stats
    if not D:
        stats["docling_empty->mineru"] += 1
        return [m.md for m in M] + tail, stats

    # --- alinhamento Húngaro ---
    cost = [[1.0] * len(M) for _ in D]
    for i, d in enumerate(D):
        for j, m in enumerate(M):
            geo = iou(d.box, m.box) if (d.box and m.box) else 0.0
            cost[i][j] = (1 - policy.align_lambda) * (1 - sim(d.text, m.text)) + (
                policy.align_lambda
            ) * (1 - geo)
    ri_ci = linear_sum_assignment(cost)
    match_d2m = {
        int(i): int(j)
        for i, j in ri_ci
        if cost[i][j] <= policy.align_tau
    }

    # esqueleto não confiável quando quase nada casa (scans rotacionados/lixo)
    nd_txt = sum(d.kind == "text" for d in D)
    nm_txt = sum(m.kind == "text" for m in M)
    if (
        garbage_frac > 0
        and nd_txt >= 3
        and nm_txt >= 3
        and len(match_d2m) < garbage_frac * min(len(D), len(M))
    ):
        stats["garbage-mineru->docling"] += 1
        return [d.md for d in D] + tail, stats

    m2d = {j: i for i, j in match_d2m.items()}

    # esqueleto: ordem do provider B (MinerU), pares resolvidos
    seq: list[tuple[float, float, str]] = []
    for j, m in enumerate(M):
        md = _pick(D[m2d[j]], m, M, policy, stats) if j in m2d else m.md
        if j not in m2d:
            stats["unilateral-mineru"] += 1
        seq.append((float(j), 0.0, md))

    # insere blocos Docling unilaterais junto ao bloco MinerU mais próximo
    centers = [center(m.box) for m in M]
    for i, d in enumerate(D):
        if i in match_d2m:
            continue
        if len(d.text) < min_len and d.kind == "text":
            stats["dropped-docling-short"] += 1
            continue
        if policy.pick_guard and d.kind == "text" and d.box is not None and (
            sum(
                m.kind == "text"
                and m.box is not None
                and contain_frac(m.box, d.box) >= 0.6
                for m in M
            ) >= 2
            or (len(d.text) >= 200 and swallows(
                d.text, [o.text for o in M if o.kind == "text"]
            ))
        ):
            stats["dropped-docling-swallowing"] += 1
            continue
        cx, cy = center(d.box)
        j = min(
            range(len(centers)),
            key=lambda k: (cx - centers[k][0]) ** 2 + (cy - centers[k][1]) ** 2,
        )
        above = cy < centers[j][1]
        seq.append((float(j) - 0.5 if above else float(j) + 0.5, cy, d.md))
        stats["unilateral-docling"] += 1
    seq.sort(key=lambda t: (t[0], t[1]))
    return [md for _, _, md in seq] + tail, stats
