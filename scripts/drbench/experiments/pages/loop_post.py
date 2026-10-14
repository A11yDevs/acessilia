#!/usr/bin/env python3
"""Post-process tree_differ_v2 predictions (*.drbench.md, blocks separated by blank lines).
--split-lines MINLEN: a text block whose lines are all >= MINLEN chars (paragraphs fused by MinerU with a
single newline) is split into one block per line, so the official matcher sees GT-like paragraphs
(a fused 1600-char block next to header/page-number blocks gets edit=1 in match_gt2pred_quick)."""
import argparse, bisect, difflib, html, re
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--inp", type=Path, required=True)
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--split-lines", type=int, default=0, metavar="MINLEN")
ap.add_argument("--detab-prose", type=float, default=0, metavar="AVG",
                help="a <table> whose non-empty cells average >= AVG chars (prose laid out in a grid) becomes one text block per row")
ap.add_argument("--resplit", type=Path, metavar="MINERU_DIR",
                help="split a text block that matches >=2 consecutive MinerU blocks at their boundaries")
ap.add_argument("--resplit-sim", type=float, default=0.9)
ap.add_argument("--resplit-punct", action="store_true", help="only cut after MinerU blocks ending in terminal punctuation")
ap.add_argument("--smallcaps", action="store_true", help="WALDoRF -> WALDORF (small caps misread as lowercase)")
ap.add_argument("--drop-labels", type=float, default=0, metavar="FRAC",
                help="page with >=8 blocks of <=3 non-digit chars making >=FRAC of all blocks (figure labels): drop them")
a = ap.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
n_split = n_detab = n_resplit = 0
SKIP = ("<table", "$$", "\\[", "|", "#", "![")


def sc_fix(m):
    w = m.group(0); low = [i for i, ch in enumerate(w) if ch.islower()]
    if (len(w) < 5 or not 1 <= len(low) <= 2 or len(w) - len(low) < 3 or (len(low) == 2 and low[1] - low[0] == 1)
            or (low[0] == 1 and len(w) < 6) or (low[-1] == len(w) - 1 and w[-1] == "s")):
        return w
    return w.upper()


def resplit(b, mb):
    """Split b where the best-matching run of >=2 consecutive MinerU blocks has boundaries."""
    if b.lstrip().startswith(SKIP) or len(b) < 80:
        return None
    best = None
    for i in range(len(mb)):
        for j in range(i + 2, min(i + 9, len(mb)) + 1):
            cat = " ".join(mb[i:j])
            if len(cat) > 1.25 * len(b): break
            if len(cat) < 0.8 * len(b) or min(map(len, mb[i:j])) < 30: continue
            sm = difflib.SequenceMatcher(None, cat, b, autojunk=False)
            r = sm.ratio()
            if r >= a.resplit_sim and (best is None or r > best[0]): best = (r, mb[i:j], sm)
    if not best: return None
    _, run, sm = best
    mbl = sm.get_matching_blocks(); starts = [m.a for m in mbl]
    cuts, pos = [], 0
    for x in run[:-1]:
        pos += len(x) + 1  # boundary offset in cat
        if a.resplit_punct and not re.search(r"[.!?:;\"”’)]\s*$", x): continue
        k = max(0, bisect.bisect_right(starts, pos) - 1); m = mbl[k]
        off = m.b + min(pos - m.a, m.size)
        sp = [q for q in (b.rfind(" ", 0, off + 1), b.find(" ", off)) if q > 0]
        if sp: cuts.append(min(sp, key=lambda q: abs(q - off)))
    cuts = sorted(set(c for c in cuts if 0 < c < len(b)))
    parts = [b[x:y].strip() for x, y in zip([0] + cuts, cuts + [len(b)])]
    return parts if len(parts) > 1 and min(map(len, parts)) >= 30 else None


def cells(row):
    return [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
for f in sorted(a.inp.glob("*.drbench.md")):
    blocks = [b for b in re.split(r"\n\s*\n", f.read_text(encoding="utf-8")) if b.strip()]
    out = []
    if a.resplit and (a.resplit / f.name).exists():
        mb = [x.replace("\n", " ") for x in re.split(r"\n\s*\n", (a.resplit / f.name).read_text(encoding="utf-8"))
              if x.strip() and not x.lstrip().startswith(SKIP)]
        nb = []
        for b in blocks:
            r = resplit(b, mb) if "\n" not in b.strip() else None
            if r: nb.extend(r); n_resplit += 1
            else: nb.append(b)
        blocks = nb
    if a.drop_labels:
        tiny = [len(b.strip()) <= 3 and not b.strip().isdigit() for b in blocks]
        if sum(tiny) >= 8 and sum(tiny) >= a.drop_labels * len(blocks):
            blocks = [b for b, t in zip(blocks, tiny) if not t]
    if a.smallcaps:
        blocks = [b if b.lstrip().startswith(("<table", "$$", "\\[")) else re.sub(r"\b[A-Z][A-Za-z]{4,}\b", sc_fix, b) for b in blocks]
    for b in blocks:
        if a.detab_prose and b.lstrip().startswith("<table"):
            rows = [[c for c in cells(r) if c] for r in re.findall(r"<tr[^>]*>(.*?)</tr>", b, re.S)]
            cs = [c for r in rows for c in r]
            if cs and sum(map(len, cs)) / len(cs) >= a.detab_prose:
                out.extend(re.sub(r"\s+", " ", " ".join(r)) for r in rows if r); n_detab += 1
                continue
        lines = [l for l in b.split("\n") if l.strip()]
        if (a.split_lines and len(lines) > 1 and not b.lstrip().startswith(("<table", "$$", "\\[", "|", "#"))
                and min(len(l) for l in lines[:-1]) >= a.split_lines):
            out.extend(lines); n_split += 1
        else:
            out.append(b)
    (a.out / f.name).write_text("\n\n".join(out) + "\n", encoding="utf-8")
print(f"split blocks: {n_split}  detab: {n_detab}  resplit: {n_resplit}")
