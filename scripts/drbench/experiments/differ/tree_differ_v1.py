#!/usr/bin/env python3
"""Tree Differ v1 (text-only): block-level alignment + merge of two *.drbench.md
predictions (Docling force-OCR, MinerU) for the same page.

Blocks = blank-line-separated Markdown chunks (HTML <table> and $$ formulas kept
whole).  The two block sequences are aligned with an ordered edit distance
(Zhang-Shasha at depth one == sequence edit distance) with relabel cost
1 - sim(text), unit insert/delete.  Pairs with sim < --tau are split into
insert+delete (unilateral).  Merge in MinerU reading order: agreed/disputed text
-> Docling text; any pair or unilateral block with table/formula -> MinerU;
unilateral Docling blocks kept only if long enough and not already present.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
from collections import Counter
from pathlib import Path

HEADER = "# Dr.DocBench page"
TABLE_RE = re.compile(r"<table", re.IGNORECASE)
FORMULA_RE = re.compile(r"\$\$|\\\[|\\\(")
IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def norm(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[#*_`|>$\\\[\]{}]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def split_blocks(md: str) -> list[str]:
    body = md.split("\n", 1)[1] if md.startswith(HEADER) else md
    body = IMG_RE.sub("", body)
    out, buf, in_table = [], [], False
    for line in body.split("\n"):
        low = line.lower()
        if "<table" in low:
            in_table = True
        if in_table:
            buf.append(line)
            if "</table>" in low:
                in_table = False
                out.append("\n".join(buf).strip()); buf = []
            continue
        if line.strip() == "":
            if buf:
                out.append("\n".join(buf).strip()); buf = []
        else:
            buf.append(line)
    if buf:
        out.append("\n".join(buf).strip())
    return [b for b in out if b]


def btype(b: str) -> str:
    if TABLE_RE.search(b):
        return "table"
    if FORMULA_RE.search(b):
        return "formula"
    if b.lstrip().startswith("#"):
        return "heading"
    return "text"


def sim(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()


def align(A: list[str], B: list[str], tau: float):
    """Ordered edit distance, relabel cost 1-sim, insert/delete cost 1.
    Returns list of ops: ('match', i, j, s) | ('del', i, None) | ('ins', None, j)."""
    n, m = len(A), len(B)
    S = [[sim(A[i], B[j]) for j in range(m)] for i in range(n)]
    D = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        D[i][0] = float(i)
    for j in range(1, m + 1):
        D[0][j] = float(j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i - 1][j] + 1, D[i][j - 1] + 1, D[i - 1][j - 1] + (1 - S[i - 1][j - 1]))
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(D[i][j] - (D[i - 1][j - 1] + 1 - S[i - 1][j - 1])) < 1e-9:
            s = S[i - 1][j - 1]
            if s >= tau:
                ops.append(("match", i - 1, j - 1, s))
            else:
                ops.append(("del", i - 1, None, s)); ops.append(("ins", None, j - 1, s))
            i, j = i - 1, j - 1
        elif i > 0 and abs(D[i][j] - (D[i - 1][j] + 1)) < 1e-9:
            ops.append(("del", i - 1, None, 0.0)); i -= 1
        else:
            ops.append(("ins", None, j - 1, 0.0)); j -= 1
    return ops[::-1]


def covered_by(a: str, tables: list[set[str]]) -> bool:
    """True if >=70% of the block's words already occur in an emitted MinerU table."""
    words = norm(a).split()
    if not words:
        return True
    return any(sum(w in t for w in words) / len(words) >= 0.7 for t in tables)


def merge(doc_md: str, min_md: str, tau: float, tau_txt: float, min_len: int):
    A, B = split_blocks(doc_md), split_blocks(min_md)  # A = Docling, B = MinerU
    ops = align(A, B, tau)
    out, kept_norm, tables, stats = [], [], [], Counter()
    for op in ops:
        kind, i, j, s = op
        if kind == "match":
            a, b = A[i], B[j]
            ta, tb = btype(a), btype(b)
            if tb in ("table", "formula") or ta in ("table", "formula"):
                pick, cls = (b if tb in ("table", "formula") else a), "disputed-type" if ta != tb else "agreed-struct"
            elif s >= tau_txt:
                pick, cls = a, "agreed"
            else:
                pick, cls = a, "disputed-content"
            stats[cls] += 1
        elif kind == "ins":  # only MinerU
            pick, cls = B[j], "unilateral-mineru"
            stats[cls] += 1
        else:  # only Docling
            a = A[i]
            if len(norm(a)) < min_len or any(sim(a, k) >= tau_txt for k in kept_norm[-3:]) or covered_by(a, tables):
                stats["dropped-docling"] += 1
                continue
            pick, cls = a, "unilateral-docling"
            stats[cls] += 1
        out.append(pick)
        kept_norm.append(pick)
        if btype(pick) == "table":
            tables.append(set(norm(pick).split()))
    total = sum(v for k, v in stats.items() if k != "dropped-docling")
    agree = (stats["agreed"] + stats["agreed-struct"]) / total if total else 0.0
    return out, stats, agree, len(A), len(B)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docling", type=Path, required=True)
    ap.add_argument("--mineru", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tau", type=float, default=0.30)
    ap.add_argument("--tau-txt", type=float, default=0.80)
    ap.add_argument("--min-len", type=int, default=40)
    a = ap.parse_args()

    ids = sorted({p.name for p in a.docling.glob("*.drbench.md")} & {p.name for p in a.mineru.glob("*.drbench.md")})
    a.out.mkdir(parents=True, exist_ok=True)
    rows, tot = [], Counter()
    for name in ids:
        doc = (a.docling / name).read_text(encoding="utf-8")
        mi = (a.mineru / name).read_text(encoding="utf-8")
        blocks, stats, agree, na, nb = merge(doc, mi, a.tau, a.tau_txt, a.min_len)
        if not blocks:  # fall back to the longer single output
            blocks = split_blocks(doc if len(norm(doc)) >= len(norm(mi)) else mi)
            stats["fallback"] += 1
        head = doc.split("\n", 1)[0] if doc.startswith(HEADER) else mi.split("\n", 1)[0]
        (a.out / name).write_text(head + "\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
        tot.update(stats)
        rows.append({"item": name.removesuffix(".drbench.md"), "n_docling": na, "n_mineru": nb,
                     "n_out": len(blocks), "agreement": f"{agree:.3f}", **{k: stats.get(k, 0) for k in
                     ("agreed", "agreed-struct", "disputed-content", "disputed-type", "unilateral-mineru",
                      "unilateral-docling", "dropped-docling")}})
    with (a.out / "decisions.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"pages={len(ids)} tau={a.tau} tau_txt={a.tau_txt} min_len={a.min_len}")
    for k, v in sorted(tot.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
