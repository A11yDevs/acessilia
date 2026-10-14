#!/usr/bin/env python3
"""Re-segment A's blocks with the VLM page's block boundaries; A's words, lines and order are kept.

A and VLM word streams are aligned (difflib). Every A line break whose position maps to a VLM block boundary
becomes a blank line (block split); with --merge, A blank lines that fall inside one VLM block (both sides of the
break aligned to that block) are removed. Tables / '$$' blocks of A are never touched.

  vlm_reseg.py --a A --vlm VLM --out OUT [--docling D --mineru M --dm 0.6] [--merge]
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_fuse import norm  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402
from vlm_page_select import strip_comment  # noqa: E402


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p and p.exists() else ""


def words(t):
    return norm(t).split()


def reseg(ta: str, tv: str, merge: bool, a_gap: int = 1):
    vb = [b for b in re.split(r"\n\s*\n", tv) if b.strip()]
    vw, vblk = [], []
    for k, b in enumerate(vb):
        w = words(b)
        vw += w
        vblk += [k] * len(w)
    # A as list of (block, lines); keep atomic blocks
    ab = [b.strip("\n") for b in re.split(r"\n\s*\n", ta) if b.strip()]
    lines, aw, line_of = [], [], []  # lines: (text, block idx, atomic)
    for bi, b in enumerate(ab):
        atomic = b.lstrip().startswith(("<table", "$$", "<"))
        for ln in (b.split("\n") if not atomic else [b]):
            lines.append((ln, bi, atomic))
            w = words(ln)
            aw += w
            line_of += [len(lines) - 1] * len(w)
    if not aw or not vw:
        return ta, 0, 0
    a2v = {}
    for i, j, n in difflib.SequenceMatcher(None, aw, vw, autojunk=False).get_matching_blocks():
        for t in range(n):
            a2v[i + t] = j + t
    first = {}
    last = {}
    for wi, li in enumerate(line_of):
        first.setdefault(li, wi)
        last[li] = wi
    out, splits, merges = [], 0, 0
    for li, (ln, bi, atomic) in enumerate(lines):
        if li:
            pbi, patom = lines[li - 1][1], lines[li - 1][2]
            sep = "\n\n\n\n\n" if pbi != bi else "\n"
            if not atomic and not patom and li - 1 in last and li in first:
                e, s = a2v.get(last[li - 1]), a2v.get(first[li])
                if e is not None and s is not None and e < s <= e + a_gap:
                    if pbi == bi and vblk[s] != vblk[e]:
                        sep, splits = "\n\n\n\n\n", splits + 1
                    elif merge and pbi != bi and vblk[s] == vblk[e]:
                        sep, merges = "\n", merges + 1
            out.append(sep)
        out.append(ln)
    return "".join(out) + "\n", splits, merges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--vlm", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--docling", type=Path)
    ap.add_argument("--mineru", type=Path)
    ap.add_argument("--dm", type=float, default=1.01, help="only pages with ratio(Docling, MinerU) < DM")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--gap", type=int, default=1, help="max VLM word gap across an A line break")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    S = M = P = 0
    for pa in sorted(a.a.glob("*.drbench.md")):
        ta, tv = read(pa), strip_comment(read(a.vlm / pa.name))
        out = ta
        if tv.strip():
            ok = True
            if a.dm <= 1.0:
                d, m = norm(read(a.docling / pa.name)), norm(read(a.mineru / pa.name))
                ok = (fuzz.ratio(d, m) / 100 if d and m else 0.0) < a.dm
            if ok:
                out, s, mg = reseg(ta, tv, a.merge, a.gap)
                S, M, P = S + s, M + mg, P + bool(s or mg)
        (a.out / pa.name).write_text(out, encoding="utf-8")
    print(f"pages changed {P}  splits {S}  merges {M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
