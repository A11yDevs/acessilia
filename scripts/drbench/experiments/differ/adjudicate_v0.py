#!/usr/bin/env python
"""Adjudicator v0: per-page router between Docling-forceOCR and MinerU outputs.

No new inference. For every page id present in BOTH prediction directories
(``<id>.drbench.md``), exactly one of the two Markdown outputs is copied to
``--out``. Decision rule (``--rule v0``, the one described in the paper):

  1. If the MinerU output contains an HTML table (``<table``) or a display /
     inline formula (``$$``, ``\\[`` or ``\\(``) -> choose MinerU. Rationale: the
     Docling pipeline flattens tables and formulas away (TEDS = 0, formula
     score = 0 on the dev subset), so MinerU is the only candidate that can
     score on those components.
  2. Else, if one output is near-empty (< 40 characters of useful text after
     stripping HTML, Markdown punctuation, the ``# Dr.DocBench page`` header
     and image references) and the other is not -> choose the non-empty one.
  3. Else -> choose Docling-forceOCR, which has the better text Edit distance
     under the official evaluator on the dev subset (78.7 vs 73.1).

``--rule agreement`` (v0b): first compute the difflib ratio between the two
normalized texts; if agreement >= ``--agree-thr`` (default 0.85) choose
Docling (the two trees agree, so prefer the better text engine), otherwise
fall back to rule v0.

Writes ``<id>.drbench.md`` and ``decisions.csv`` (id, choice, reason,
len_docling, len_mineru, mineru_has_table, mineru_has_formula, agreement).
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import shutil
from collections import Counter
from pathlib import Path

TABLE_RE = re.compile(r"<table", re.IGNORECASE)
FORMULA_RE = re.compile(r"\$\$|\\\[|\\\(")
IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
NEAR_EMPTY = 40


def useful_text(md: str) -> str:
    md = md.replace("# Dr.DocBench page", "")
    md = IMG_RE.sub(" ", md)
    md = re.sub(r"<[^>]+>", " ", md)
    md = re.sub(r"[#*_`|>$\\\[\]{}()\-]", " ", md)
    return re.sub(r"\s+", " ", md).strip()


def norm_text(md: str) -> str:
    """Same normalization as scripts/eval_summary.py (analysis (c))."""
    md = re.sub(r"<[^>]+>", " ", md)
    md = re.sub(r"[#*_`|>$\\\[\]{}]", " ", md)
    return re.sub(r"\s+", " ", md).strip().lower()


def decide_v0(doc: str, min_: str) -> tuple[str, str]:
    if TABLE_RE.search(min_):
        return "mineru", "mineru_has_table"
    if FORMULA_RE.search(min_):
        return "mineru", "mineru_has_formula"
    ld, lm = len(useful_text(doc)), len(useful_text(min_))
    if ld < NEAR_EMPTY <= lm:
        return "mineru", "docling_near_empty"
    if lm < NEAR_EMPTY <= ld:
        return "docling", "mineru_near_empty"
    return "docling", "default_docling_text"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docling", type=Path, required=True)
    ap.add_argument("--mineru", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--rule", choices=["v0", "agreement"], default="v0")
    ap.add_argument("--agree-thr", type=float, default=0.85)
    a = ap.parse_args()

    ids_d = {p.name for p in a.docling.glob("*.drbench.md")}
    ids_m = {p.name for p in a.mineru.glob("*.drbench.md")}
    ids = sorted(ids_d & ids_m)
    print(f"docling={len(ids_d)} mineru={len(ids_m)} common={len(ids)} "
          f"only_docling={len(ids_d - ids_m)} only_mineru={len(ids_m - ids_d)}")

    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in ids:
        doc = (a.docling / name).read_text(encoding="utf-8")
        min_ = (a.mineru / name).read_text(encoding="utf-8")
        agree = ""
        if a.rule == "agreement":
            agree = difflib.SequenceMatcher(None, norm_text(doc), norm_text(min_), autojunk=False).ratio()
            if agree >= a.agree_thr:
                choice, reason = "docling", f"agreement>={a.agree_thr}"
            else:
                choice, reason = decide_v0(doc, min_)
            agree = f"{agree:.4f}"
        else:
            choice, reason = decide_v0(doc, min_)
        shutil.copyfile((a.docling if choice == "docling" else a.mineru) / name, a.out / name)
        rows.append({
            "id": name.removesuffix(".drbench.md"), "choice": choice, "reason": reason,
            "len_docling": len(useful_text(doc)), "len_mineru": len(useful_text(min_)),
            "mineru_has_table": int(bool(TABLE_RE.search(min_))),
            "mineru_has_formula": int(bool(FORMULA_RE.search(min_))),
            "agreement": agree,
        })

    with open(a.out / "decisions.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"rule={a.rule} n={len(rows)} choice={dict(Counter(r['choice'] for r in rows))}")
    for k, v in sorted(Counter(r["reason"] for r in rows).items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
