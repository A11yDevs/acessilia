#!/usr/bin/env python3
"""Score dev-986 runs on a fixed document split (tune = 2/3, holdout = 1/3 by md5 of doc id).
evalai_style_no_cdm = mean(text, teds, reading_order) over the windows of each subset.
  python3 scripts/loop_score.py BASE RUN [RUN ...]   (deltas are vs BASE)

The split and the acceptance criteria live in ``docstruct.evaluation.holdout`` so
the discipline is testable and shared, not reimplemented per script.
"""
import json
import os
import sys

from docstruct.evaluation.holdout import LOOP_METRICS, evaluate_candidate, score

FULL = os.environ.get("DRBENCH_FULL", "/raid/user_marcospaulo/drdocbench/runs/dev-full")
MET = LOOP_METRICS


def load(r):
    return {w["window"]: w for w in json.load(open(f"{FULL}/{r}/reports/official_w1-md2md.json"))["windows"]}


runs = sys.argv[1:]
base_windows = load(runs[0])
base = {s: score(base_windows, s) for s in ("tune", "hold", "all")}
for r in runs:
    W = load(r)
    cells = []
    for s in ("tune", "hold", "all"):
        sc = score(W, s)
        cells.append(f"{s} {sc['evalai']:.2f} ({sc['evalai'] - base[s]['evalai']:+.2f}) "
                     f"t{sc['text'] - base[s]['text']:+.2f} r{sc['reading_order'] - base[s]['reading_order']:+.2f} "
                     f"T{sc['teds'] - base[s]['teds']:+.2f}")
    verdict = evaluate_candidate(base_windows, W)
    print(f"{r:28s} | " + " | ".join(cells) + f" | {'ACCEPTED' if verdict.accepted else 'REJECTED'}: {verdict.reason}")
