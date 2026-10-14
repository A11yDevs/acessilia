"""tailjoin.py 'end' mode, conditioned on the page-number position (pnpos.py): the GT keeps the running header
before a BOTTOM page number in 91% of dev pages (130/143) but is ~70/30 when the number is at the top, so the
tail is joined only when the number is not known to be at the bottom; at the bottom, BOT=keep leaves it, BOT=hdr
moves the number(s) last.  usage: tailjoin3.py SRC OUT POS.json MAXLEN K BOT"""
import json, re, sys
from pathlib import Path
src, out, P, ML, K, BOT = Path(sys.argv[1]), Path(sys.argv[2]), json.load(open(sys.argv[3])), int(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
num = lambda b: re.fullmatch(r"[\divxlcIVXLC]{1,5}", b.strip()) is not None
short = lambda b: len(b.strip()) <= ML and "\n" not in b.strip()
out.mkdir(parents=True, exist_ok=True); n = m = 0
for p in src.glob("*.drbench.md"):
    bl = [b.strip("\n") for b in re.split(r"\n\s*\n", p.read_text(encoding="utf-8")) if b.strip()]
    j = len(bl)
    while j > 1 and len(bl) - j < K and short(bl[j - 1]): j -= 1
    tail = bl[j:]
    if len(tail) >= 2 and j >= 1 and (num(tail[0]) or num(tail[-1])):
        if P.get(p.name.split(".drbench")[0]) == "bot":
            if BOT == "hdr":
                bl = bl[:j] + [b for b in tail if not num(b)] + [b for b in tail if num(b)]
            m += 1
        else:
            bl = bl[:j] + [" ".join(b.strip() for b in tail)]; n += 1
    (out / p.name).write_text("\n\n\n\n\n".join(bl) + "\n", encoding="utf-8")
print("joined", n, "bottom", m)
