#!/usr/bin/env python3
"""Swap whole pages of a differ run for a stronger single-source rendition (e.g. MinerU2.5 VLM).

GT-free criterion: pages where Docling and MinerU disagree the most (low difflib ratio of their
normalised markdown) are the fuzzy/hard pages where the fused output inherits bad OCR; there the
alt source (full-page VLM) replaces the fused page. Works for dev and test alike.

Usage:
  python scripts/page_swap.py --base runs/dev-full/v16-hyb-rec300/predictions \
      --alt runs/dev-full/mineru-vlm/predictions --docling runs/dev-full/docling+rot/predictions \
      --mineru runs/dev-full/mineru-hyb+rot/predictions --out runs/dev-full/v18-pswap/predictions \
      [--agree-thr 0.45] [--list swapped.txt]
"""
import argparse
import difflib
import re
import shutil
import sys
from pathlib import Path


def nrm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[#*_`>|<>/-]", "", s)).strip().lower()


def agreement(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, nrm(a), nrm(b), autojunk=False).ratio()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--alt", type=Path, required=True)
    ap.add_argument("--docling", type=Path, required=True)
    ap.add_argument("--mineru", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--agree-thr", type=float, default=0.45)
    ap.add_argument("--min-alt-frac", type=float, default=0.3,
                    help="alt page must have at least this fraction of the base page's text length")
    ap.add_argument("--list", type=Path, default=None, help="write the swapped page ids here")
    a = ap.parse_args()

    a.out.mkdir(parents=True, exist_ok=True)
    swapped, kept, no_alt = [], 0, 0
    for p in sorted(a.base.glob("*.drbench.md")):
        stem = p.name.removesuffix(".drbench.md")
        dst = a.out / p.name
        dp, mp, altp = a.docling / p.name, a.mineru / p.name, a.alt / p.name
        swap = False
        if dp.exists() and mp.exists():
            ag = agreement(dp.read_text(encoding="utf-8"), mp.read_text(encoding="utf-8"))
            if ag < a.agree_thr:
                if altp.exists():
                    alt_md = altp.read_text(encoding="utf-8")
                    base_md = p.read_text(encoding="utf-8")
                    if len(nrm(alt_md)) >= a.min_alt_frac * len(nrm(base_md)):
                        dst.write_text(alt_md, encoding="utf-8")
                        swapped.append(f"{stem}\t{ag:.3f}")
                        swap = True
                else:
                    no_alt += 1
        if not swap:
            shutil.copyfile(p, dst)
            kept += 1
    if a.list:
        a.list.parent.mkdir(parents=True, exist_ok=True)
        a.list.write_text("\n".join(swapped) + ("\n" if swapped else ""), encoding="utf-8")
    print(f"pages: {kept + len(swapped)} total | swapped {len(swapped)} (agree<{a.agree_thr}) | "
          f"kept {kept} | low-agree without alt {no_alt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
