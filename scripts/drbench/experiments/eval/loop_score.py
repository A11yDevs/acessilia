#!/usr/bin/env python3
"""Score dev-986 runs on a fixed document split (tune = 2/3, holdout = 1/3 by md5 of doc id).
evalai_style_no_cdm = mean(text, teds, reading_order) over the windows of each subset.
  python3 scripts/loop_score.py BASE RUN [RUN ...]   (deltas are vs BASE)"""
import hashlib, json, os, statistics as st, sys
FULL = os.environ.get("DRBENCH_FULL", "/raid/user_marcospaulo/drdocbench/runs/dev-full")
MET = ("text", "reading_order", "teds")

def load(r):
    return {w["window"]: w for w in json.load(open(f"{FULL}/{r}/reports/official_w1-md2md.json"))["windows"]}

def part(win):
    return "hold" if int(hashlib.md5(win.split("_page_")[0].encode()).hexdigest(), 16) % 3 == 0 else "tune"

def score(W, sub):
    out = {}
    for m in MET:
        v = [w[m] for k, w in W.items() if (sub == "all" or part(k) == sub) and w[m] is not None]
        out[m] = st.mean(v) if v else float("nan")
    out["evalai"] = st.mean(out[m] for m in MET)
    return out

runs = sys.argv[1:]
base = {s: score(load(runs[0]), s) for s in ("tune", "hold", "all")}
for r in runs:
    W = load(r)
    cells = []
    for s in ("tune", "hold", "all"):
        sc = score(W, s)
        cells.append(f"{s} {sc['evalai']:.2f} ({sc['evalai'] - base[s]['evalai']:+.2f}) "
                     f"t{sc['text'] - base[s]['text']:+.2f} r{sc['reading_order'] - base[s]['reading_order']:+.2f} "
                     f"T{sc['teds'] - base[s]['teds']:+.2f}")
    print(f"{r:28s} | " + " | ".join(cells))
