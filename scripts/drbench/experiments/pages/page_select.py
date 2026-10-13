#!/usr/bin/env python3
"""Per-page selection between the differ output (A) and the whole-page VLM OCR (B), adjudicated by agreement
with the two provider trees (Docling, MinerU): pick B when its text agrees with the providers clearly better than A.

  page_select.py --a DIR --b DIR --refs D1 D2 --out DIR [--margin 0.02] [--feat feats.jsonl]
Similarity = rapidfuzz ratio on normalised text (no markup, lowercase, alnum + spaces).
"""
import argparse
import json
import re
import shutil
from pathlib import Path

from rapidfuzz import fuzz

TAG = re.compile(r"<[^>]+>|\$+|\\[a-z]+|[#*_`|]")


def norm(t: str) -> str:
    t = TAG.sub(" ", t).lower()
    return " ".join(re.sub(r"[^\w]+", " ", t).split())


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--b", type=Path, required=True)
    ap.add_argument("--refs", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--margin", type=float, default=0.02)
    ap.add_argument("--feat", type=Path)
    a = ap.parse_args()
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
    nb = 0
    feats = []
    for pa in sorted(a.a.glob("*.drbench.md")):
        ta, tb = read(pa), read(a.b / pa.name)
        na, nbb = norm(ta), norm(tb)
        refs = [norm(read(r / pa.name)) for r in a.refs]
        sa = [fuzz.ratio(na, r) / 100 for r in refs]
        sb = [fuzz.ratio(nbb, r) / 100 for r in refs] if nbb else [0.0] * len(refs)
        ab = fuzz.ratio(na, nbb) / 100 if nbb else 0.0
        pick_b = bool(nbb) and sum(sb) / len(sb) > sum(sa) / len(sa) + a.margin
        nb += pick_b
        feats.append({"page": pa.name, "sa": sa, "sb": sb, "ab": ab, "la": len(na), "lb": len(nbb),
                      "tab_a": ta.count("<table"), "tab_b": tb.count("<table"), "pick_b": pick_b})
        if a.out:
            shutil.copy(a.b / pa.name if pick_b else pa, a.out / pa.name)
    if a.feat:
        a.feat.write_text("".join(json.dumps(f) + "\n" for f in feats))
    print(f"pages {len(feats)}  picked B: {nb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
