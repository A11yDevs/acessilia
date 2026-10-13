#!/usr/bin/env python3
"""Guard against generation loops in the differ output A (MinerU/VLM degenerate repetition, e.g. "5 5 5 5 ..." or
one sentence repeated 10x on a blank page).

loops : inside a block, an n-gram (n <= --max-n tokens) repeated k >= --reps times in a row is cut down to the
        largest consecutive repeat count that Docling or the VLM page shows for it (at least 1).
blank : with --blank, a page where Docling has no text and the VLM says the page has no text (its output is only
        "no text" commentary) is emptied.

  rep_guard.py --a A --docling D --vlm V --out OUT [--reps 5] [--max-n 12] [--blank]
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_fuse import norm  # noqa: E402
from vlm_page_select import strip_comment  # noqa: E402


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def max_run(ref: list, g: tuple) -> int:
    n, best = len(g), 0
    i = 0
    while i + n <= len(ref):
        if tuple(ref[i:i + n]) == g:
            k = 1
            while tuple(ref[i + k * n:i + (k + 1) * n]) == g:
                k += 1
            best = max(best, k)
            i += k * n
        else:
            i += 1
    return best


def collapse(block: str, refs: list, reps: int, max_n: int):
    parts = re.split(r"(\s+)", block)
    toks = parts[0::2]
    seps = parts[1::2] + [""]
    key = [norm(t) for t in toks]
    out, i, cut = [], 0, 0
    while i < len(toks):
        done = False
        if key[i]:
            for n in range(1, max_n + 1):
                g = tuple(key[i:i + n])
                if len(g) < n or not all(g):
                    break
                k = 1
                while tuple(key[i + k * n:i + (k + 1) * n]) == g:
                    k += 1
                if k >= reps:
                    keep = max([1] + [max_run(r, g) for r in refs])
                    if keep < k:
                        out += [t + s for t, s in zip(toks[i:i + keep * n], seps[i:i + keep * n])]
                        cut += (k - keep) * n
                        i += k * n
                        done = True
                        break
        if not done:
            out.append(toks[i] + seps[i])
            i += 1
    return "".join(out), cut


def main() -> int:
    ap = argparse.ArgumentParser()
    for k in ("a", "docling", "vlm", "out"):
        ap.add_argument(f"--{k}", type=Path, required=True)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--max-n", type=int, default=12)
    ap.add_argument("--blank", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    P = C = B = 0
    for pa in sorted(a.a.glob("*.drbench.md")):
        ta = read(pa)
        td, tvr = read(a.docling / pa.name), read(a.vlm / pa.name)
        out = ta
        if a.blank and norm(ta) and not norm(td) and tvr.strip() and not strip_comment(tvr).strip():
            out, B = "\n", B + 1
        else:
            refs = [norm(td).split(), norm(tvr).split()]
            bl, cut = [], 0
            for b in re.split(r"(\n\s*\n)", ta):
                if b.strip() and not b.lstrip().startswith(("<table", "$$", "<")):
                    b, c = collapse(b, refs, a.reps, a.max_n)
                    cut += c
                bl.append(b)
            if cut:
                out, P, C = "".join(bl), P + 1, C + cut
        (a.out / pa.name).write_text(out, encoding="utf-8")
    print(f"loop pages {P}  tokens cut {C}  blank pages {B}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
