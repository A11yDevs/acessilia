#!/usr/bin/env python3
"""Fuse whole-page VLM OCR (B) with the differ output (A) at block level.

modes:
  order : B's blocks, reordered by the order of their matched A blocks (A carries the decor-tail / RO conventions)
  head  : as order, + B heading markup ('#') copied from the matched A block (A has the GT heading conventions)
  swap  : A's blocks and order; each A block whose best B block matches (>= --sim) takes B's text (A's '#' kept);
          tables swapped only with --swap-tables
Blocks = chunks separated by blank lines. Match = rapidfuzz ratio on normalised text >= --sim.
"""
import argparse
import re
from pathlib import Path

from rapidfuzz import fuzz

TAG = re.compile(r"<[^>]+>|\$+|\\[a-z]+|[#*_`|]")


def norm(t: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", TAG.sub(" ", t).lower()).split())


def blocks(t: str):
    return [b.strip("\n") for b in re.split(r"\n\s*\n", t) if b.strip()]


def swap(A, Bk, sim, tables):
    nb = [norm(x) for x in Bk]
    out = []
    for x in A:
        is_tab = x.lstrip().startswith("<table")
        if is_tab and not tables:
            out.append(x)
            continue
        nx = norm(x)
        best, bj = 0.0, -1
        for j, y in enumerate(nb):
            if nx and y and is_tab == Bk[j].lstrip().startswith("<table"):
                s = fuzz.ratio(nx, y) / 100
                if s > best:
                    best, bj = s, j
        if best < sim:
            out.append(x)
            continue
        y = re.sub(r"^\s*#+\s*", "", Bk[bj]).strip()
        h = re.match(r"^\s*#+\s*", x)
        out.append((h[0] if h else "") + y)
    return out


def fuse(ta: str, tb: str, mode: str, sim: float, tables: bool = False) -> str:
    A, Bk = blocks(ta), blocks(tb)
    if not Bk:
        return ta
    if mode == "swap":
        return "\n\n\n\n\n".join(swap(A, Bk, sim, tables)) + "\n"
    na = [norm(x) for x in A]
    keys, out, last = [], [], -1.0
    for j, b in enumerate(Bk):
        nb = norm(b)
        best, bi = 0.0, -1
        for i, x in enumerate(na):
            if not x or not nb:
                continue
            s = fuzz.ratio(nb, x) / 100
            if s > best:
                best, bi = s, i
        if best >= sim:
            k = float(bi)
            if mode == "head":
                hb, ha = b.lstrip().startswith("#"), A[bi].lstrip().startswith("#")
                if hb and not ha:
                    b = re.sub(r"^\s*#+\s*", "", b)
                elif ha and not hb and "\n" not in b:
                    b = A[bi][: len(A[bi]) - len(A[bi].lstrip("#"))].strip() + " " + b
        else:
            k = last + 1e-3
        last = k
        keys.append((k, j))
        out.append(b)
    order = [j for _, j in sorted(keys)]
    return "\n\n\n\n\n".join(out[j] for j in order) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--b", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", default="order", choices=["order", "head", "swap"])
    ap.add_argument("--sim", type=float, default=0.6)
    ap.add_argument("--swap-tables", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    n = 0
    for pa in sorted(a.a.glob("*.drbench.md")):
        pb = a.b / pa.name
        ta = pa.read_text(encoding="utf-8")
        tb = pb.read_text(encoding="utf-8") if pb.exists() else ""
        (a.out / pa.name).write_text(fuse(ta, tb, a.mode, a.sim, a.swap_tables) if tb.strip() else ta, encoding="utf-8")
        n += bool(tb.strip())
    print(f"fused {n} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
