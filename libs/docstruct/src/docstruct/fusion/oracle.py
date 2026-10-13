"""Oráculo por bloco: teto de qualquer seletor por bloco e taxonomia de perda.

Porta de ``block_oracle.py`` do Dr.DocBench (PR #125).

Para cada bloco de texto do ground truth, o melhor bloco correspondente de cada
provider é pontuado com o ratio difflib sobre o texto normalizado. O oráculo por
bloco escolhe, por bloco, o melhor provider — o teto de qualquer seletor por
bloco sobre essas fontes. A folga (``headroom``) é ``oráculo - differ``: o que um
adjudicador perfeito poderia acrescentar.

Tabelas e fórmulas ficam fora do oráculo de texto (métricas separadas, sempre
herdadas do MinerU nas fusões); suas contagens no GT são reportadas para
dimensionamento.

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter

from docstruct.text.normalize import norm

TABLE_RE = re.compile(r"<table", re.I)
FORMULA_RE = re.compile(r"\$\$|\\\[")

# Blocos de GT mais curtos que isto não entram no oráculo de texto.
MIN_GT_TEXT_LEN = 20

# Limiar de folga para contar uma página como "com folga".
HEADROOM_PAGE_THR = 0.05

# Abaixo disto o differ já está no oráculo.
AT_ORACLE_THR = 0.005


def kind_of(block: str) -> str:
    """Classifica um bloco do GT: ``"table"``, ``"formula"`` ou ``"text"``."""
    if TABLE_RE.search(block):
        return "table"
    if FORMULA_RE.search(block):
        return "formula"
    return "text"


def best_score(g: str, pred_blocks: list[str], sm: difflib.SequenceMatcher) -> float:
    """Melhor ratio de ``g`` contra qualquer bloco de ``pred_blocks``.

    ``sm`` é um ``SequenceMatcher`` reutilizado (``seq1`` já deve ser ``g``).
    """
    best = 0.0
    for p in pred_blocks:
        sm.set_seq2(p)
        if sm.real_quick_ratio() > best and sm.quick_ratio() > best:
            r = sm.ratio()
            if r > best:
                best = r
    return best


def page_scores(
    gt_blocks: list[str],
    pred_norm: dict[str, list[str]],
    sm: difflib.SequenceMatcher,
) -> dict[str, float]:
    """Score médio por provider para uma página (``nan`` se não há blocos de GT).

    Nota: o script original não define ``seq1`` antes de chamar ``best_score``,
    então as colunas ``docling``/``mineru``/``differ`` do ``per_page.csv`` saem
    todas ``0.0``. Aqui ``seq1`` é definido por bloco de GT, que é o
    comportamento pretendido. As colunas ``oracle``/``headroom`` do script já
    eram calculadas corretamente e são idênticas.
    """
    out: dict[str, float] = {}
    for name, blocks in pred_norm.items():
        vals = []
        for g in gt_blocks:
            sm.set_seq1(g)
            vals.append(best_score(g, blocks, sm))
        out[name] = sum(vals) / len(vals) if vals else float("nan")
    return out


def gt_text_blocks(gt_blocks: list[str]) -> list[str]:
    """Blocos de texto do GT com comprimento normalizado suficiente."""
    return [
        norm(b)
        for b in gt_blocks
        if kind_of(b) == "text" and len(norm(b)) >= MIN_GT_TEXT_LEN
    ]


def oracle_page(
    gt_text: list[str],
    pred_norm: dict[str, list[str]],
    sm: difflib.SequenceMatcher,
) -> dict[str, float]:
    """Oráculo e folga de uma página.

    ``pred_norm`` deve conter as chaves ``"docling"``, ``"mineru"`` e
    ``"differ"``. Devolve ``{"oracle", "headroom"}`` (médias por bloco de GT).
    """
    oracle_vals: list[float] = []
    head: list[float] = []
    for g in gt_text:
        sm.set_seq1(g)
        sd = best_score(g, pred_norm["docling"], sm)
        smn = best_score(g, pred_norm["mineru"], sm)
        sfd = best_score(g, pred_norm["differ"], sm)
        oracle_vals.append(max(sd, smn))
        head.append(max(sd, smn) - sfd)
    n = len(oracle_vals)
    return {
        "oracle": sum(oracle_vals) / n if n else float("nan"),
        "headroom": sum(head) / n if n else float("nan"),
    }


def summarize(rows: list[dict]) -> dict:
    """Agrega as linhas por página em um resumo.

    Devolve médias de ``docling``/``mineru``/``differ``/``oracle``/``headroom``
    e as contagens de páginas com folga e já no oráculo.
    """
    n = len(rows)
    if not n:
        return {"n": 0}
    agg: Counter = Counter()
    for r in rows:
        for key in ("docling", "mineru", "differ", "oracle", "headroom"):
            agg[key] += r[key]
    with_headroom = sum(1 for r in rows if r["headroom"] >= HEADROOM_PAGE_THR)
    at_oracle = sum(1 for r in rows if r["headroom"] < AT_ORACLE_THR)
    return {
        "n": n,
        "docling": agg["docling"] / n,
        "mineru": agg["mineru"] / n,
        "differ": agg["differ"] / n,
        "oracle": agg["oracle"] / n,
        "headroom": agg["headroom"] / n,
        "pages_with_headroom": with_headroom,
        "pages_with_headroom_pct": 100 * with_headroom / n,
        "pages_at_oracle": at_oracle,
    }
