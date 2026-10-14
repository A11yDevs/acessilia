#!/usr/bin/env python3
"""Append the page number when A lacks it: dots.ocr Page-header / Page-footer elements whose text is a bare
(arabic or roman) number, absent from A, are added as the last block(s) (GT keeps page numbers, last).
Dev-986 fastscore on v28c: 29 pages, tune +0.23, hold +0.09 (LOOP.md #22).

  pagenum_add.py --a A --raw DOTS_RAW.jsonl --out OUT
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dots_page_ocr import parse  # noqa: E402
from page_fuse import norm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    els = {f"{r['doc']}_p{r['page']}": (r["finish"], r["text"]) for r in map(json.loads, a.raw.open(encoding="utf-8"))}
    n = 0
    for pa in sorted(a.a.glob("*.drbench.md")):
        t = pa.read_text(encoding="utf-8")
        out = t
        fin, raw = els.get(pa.name.split(".drbench")[0], (None, ""))
        # A already has a (possibly misread) page-number-like block: leave it
        has_num = any(len(b.strip()) <= 5 and re.search(r"\d", b) for b in re.split(r"\n\s*\n", t))
        if fin == "stop" and not has_num:
            add = [s for x in parse(raw) if x.get("category") in ("Page-header", "Page-footer")
                   for s in [(x.get("text") or "").strip()]
                   if re.fullmatch(r"[\divxlcIVXLC]+", s) and f" {norm(s)} " not in f" {norm(t)} "]
            if add:
                out, n = t.rstrip("\n") + "\n\n\n\n\n" + "\n\n\n\n\n".join(add) + "\n", n + 1
        (a.out / pa.name).write_text(out, encoding="utf-8")
    print(f"page numbers added on {n} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
