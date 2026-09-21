#!/usr/bin/env python
"""Adjudicator v1: component-aware per-page router between Docling and MinerU.

Differences from v0 (scripts/adjudicate_v0.py): both engines now emit HTML
tables and ``$$`` formulas (structured canonical mapping), so "MinerU has a
table" is no longer a reason on its own. Rules, in order:

  1. near-empty: if one output has < 40 chars of useful text and the other
     does not -> choose the non-empty one (MinerU returns nothing for
     picture-only pages; Docling force-OCR still reads captions/page numbers).
  2. tables: if exactly one output has an HTML table -> choose it; if both
     have one -> ``--table-pref`` (default mineru).
  3. formulas: if exactly one output has a display formula -> choose it; if
     both -> ``--formula-pref`` (default mineru).
  4. default: ``--text-pref`` (default docling; better text Edit on dev).

Writes ``<id>.drbench.md`` (+ ``<id>.blocks.json`` when present in the chosen
run) and ``decisions.csv``.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adjudicate_v0 import FORMULA_RE, NEAR_EMPTY, TABLE_RE, useful_text  # noqa: E402


def decide_v1(doc: str, min_: str, *, table_pref: str, formula_pref: str, text_pref: str) -> tuple[str, str]:
    ld, lm = len(useful_text(doc)), len(useful_text(min_))
    if ld < NEAR_EMPTY <= lm:
        return "mineru", "docling_near_empty"
    if lm < NEAR_EMPTY <= ld:
        return "docling", "mineru_near_empty"
    td, tm = bool(TABLE_RE.search(doc)), bool(TABLE_RE.search(min_))
    if td != tm:
        return ("docling", "only_docling_table") if td else ("mineru", "only_mineru_table")
    if td and tm:
        return table_pref, f"both_table->{table_pref}"
    fd, fm = bool(FORMULA_RE.search(doc)), bool(FORMULA_RE.search(min_))
    if fd != fm:
        return ("docling", "only_docling_formula") if fd else ("mineru", "only_mineru_formula")
    if fd and fm:
        return formula_pref, f"both_formula->{formula_pref}"
    return text_pref, f"default_{text_pref}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docling", type=Path, required=True)
    ap.add_argument("--mineru", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--table-pref", choices=["docling", "mineru"], default="mineru")
    ap.add_argument("--formula-pref", choices=["docling", "mineru"], default="mineru")
    ap.add_argument("--text-pref", choices=["docling", "mineru"], default="docling")
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
        choice, reason = decide_v1(
            doc, min_, table_pref=a.table_pref, formula_pref=a.formula_pref, text_pref=a.text_pref
        )
        src = a.docling if choice == "docling" else a.mineru
        shutil.copyfile(src / name, a.out / name)
        blocks = src / name.replace(".drbench.md", ".blocks.json")
        if blocks.exists():
            shutil.copyfile(blocks, a.out / blocks.name)
        rows.append({
            "id": name.removesuffix(".drbench.md"), "choice": choice, "reason": reason,
            "len_docling": len(useful_text(doc)), "len_mineru": len(useful_text(min_)),
            "docling_has_table": int(bool(TABLE_RE.search(doc))),
            "mineru_has_table": int(bool(TABLE_RE.search(min_))),
            "docling_has_formula": int(bool(FORMULA_RE.search(doc))),
            "mineru_has_formula": int(bool(FORMULA_RE.search(min_))),
        })

    with open(a.out / "decisions.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"v1 n={len(rows)} choice={dict(Counter(r['choice'] for r in rows))}")
    for k, v in sorted(Counter(r["reason"] for r in rows).items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
