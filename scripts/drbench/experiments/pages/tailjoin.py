"""Join the trailing short blocks (running header / footer / page number, rendered last) into one block, so their
mutual order (annotator-dependent in the GT) cannot cost RO.  usage: tailjoin.py SRC OUT MODE MAXLEN K
MODE: num (one of them is a bare number) | end (the first or last one is a bare number) | any"""
import re, sys
from pathlib import Path
src, out, mode, ML, K = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
num = lambda b: re.fullmatch(r"[\divxlcIVXLC]{1,5}", b.strip()) is not None
short = lambda b: len(b.strip()) <= ML and "\n" not in b.strip()
out.mkdir(parents=True, exist_ok=True); n = 0
for p in src.glob("*.drbench.md"):
    bl = [b.strip("\n") for b in re.split(r"\n\s*\n", p.read_text(encoding="utf-8")) if b.strip()]
    j = len(bl)
    while j > 1 and len(bl) - j < K and short(bl[j - 1]): j -= 1
    tail = bl[j:]
    if len(tail) >= 2 and j >= 1 and (mode == "any" or (mode == "num" and any(map(num, tail))) or (mode == "end" and (num(tail[0]) or num(tail[-1])))):
        bl = bl[:j] + [" ".join(b.strip() for b in tail)]; n += 1
    (out / p.name).write_text("\n\n\n\n\n".join(bl) + "\n", encoding="utf-8")
print("changed", n)
