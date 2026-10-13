#!/usr/bin/env python3
"""Drop duplicate fragment blocks left by the differ (e.g. Docling line fragments re-emitted next to the merged
MinerU paragraph): a text block whose normalised words all occur, contiguously, inside another (longer) text block
of the same page is removed. Tables / '$$' blocks are never touched or used.

  dedup_blocks.py --a A --out OUT [--min-words 2] [--fuzzy 0] [--win 0]
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_fuse import norm  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402


def dedup(t: str, min_words: int, fz: float, win: int = 0):
    bl = [b.strip("\n") for b in re.split(r"\n\s*\n", t) if b.strip()]
    nb = [None if b.lstrip().startswith(("<table", "$$", "<")) else " " + norm(b) + " " for b in bl]
    keep, n = [], 0
    for i, b in enumerate(bl):
        x = nb[i]
        drop = False
        if x and len(x.split()) >= min_words:
            for j, y in enumerate(nb):
                if j == i or not y or len(y) <= len(x) or (win and abs(j - i) > win):
                    continue
                if x in y or (fz and fuzz.partial_ratio(x, y) / 100 >= fz):
                    drop = True
                    break
        if drop:
            n += 1
        else:
            keep.append(b)
    return "\n\n\n\n\n".join(keep) + "\n", n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-words", type=int, default=2)
    ap.add_argument("--win", type=int, default=0, help="only look at blocks within WIN positions (0 = whole page)")
    ap.add_argument("--fuzzy", type=float, default=0.0, help="also drop if partial_ratio >= FUZZY (0 = exact only)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    N = P = 0
    for pa in sorted(a.a.glob("*.drbench.md")):
        t = pa.read_text(encoding="utf-8")
        out, n = dedup(t, a.min_words, a.fuzzy, a.win)
        N, P = N + n, P + bool(n)
        (a.out / pa.name).write_text(out if n else t, encoding="utf-8")
    print(f"pages changed {P}  blocks dropped {N}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
