#!/usr/bin/env python3
"""Word-level 3-way vote (ROVER-like) on top of the differ output A.

Each A word that the whole-page VLM OCR reads differently (difflib alignment of the page's word streams, 1:1
replacements only) is replaced by the VLM word when the VLM word is attested in a provider page (Docling or
MinerU) and the A word is attested in at most --max-a providers; both words must be close (char ratio >= --sim),
so only OCR-confusion fixes ("Qz"->"Q2", "Ill"->"III") pass, never rewrites.

  word_vote.py --a A --vlm VLM --docling D --mineru M --out OUT [--sim 0.6] [--max-a 1]
"""
import argparse
import difflib
import re
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz

WORD = re.compile(r"[^\s<>$|*_#]+")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def key(w: str) -> str:
    return w.strip(".,;:!?()[]'\"“”‘’")


def vote(ta, tv, d, m, sim, max_a):
    am = list(WORD.finditer(ta))
    aw, vw = [key(x[0]) for x in am], [key(x) for x in WORD.findall(tv)]
    cd, cm = Counter(key(x) for x in WORD.findall(d)), Counter(key(x) for x in WORD.findall(m))
    reps = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, vw, autojunk=False).get_opcodes():
        if op != "replace" or i2 - i1 != j2 - j1:
            continue
        for i, j in zip(range(i1, i2), range(j1, j2)):
            a, v = aw[i], vw[j]
            if not a or not v or a == v or fuzz.ratio(a, v) / 100 < sim:
                continue
            if (cd[v] > 0 or cm[v] > 0) and (cd[a] > 0) + (cm[a] > 0) <= max_a:
                s = am[i]
                k = s[0].find(a)
                reps.append((s.start() + k, s.start() + k + len(a), v))
    for st, en, v in sorted(reps, reverse=True):
        ta = ta[:st] + v + ta[en:]
    return ta, len(reps)


def main() -> int:
    ap = argparse.ArgumentParser()
    for k in ("a", "vlm", "docling", "mineru", "out"):
        ap.add_argument(f"--{k}", type=Path, required=True)
    ap.add_argument("--sim", type=float, default=0.6)
    ap.add_argument("--max-a", type=int, default=1)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    n = 0
    for pa in sorted(a.a.glob("*.drbench.md")):
        ta, tv = read(pa), read(a.vlm / pa.name)
        if tv.strip():
            ta, k = vote(ta, tv, read(a.docling / pa.name), read(a.mineru / pa.name), a.sim, a.max_a)
            n += k
        (a.out / pa.name).write_text(ta, encoding="utf-8")
    print(f"word replacements: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
