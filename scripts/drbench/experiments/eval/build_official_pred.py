#!/usr/bin/env python
"""Build DrDocBench multipage-evaluator prediction tree from a flat run dir.

pred_root/<SUBJECT>/<uuid>_page_N-N.md  (window of 1 page) <- runs/dev/<run>/predictions/<uuid>_pN.drbench.md
"""
import json
import shutil
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[1]
run = sys.argv[1]
subset = json.loads((WS / "runs/dev/subset.json").read_text())
src = WS / "runs/dev" / run / "predictions"
dst = WS / "runs/dev" / run / "official_pred"
if dst.exists():
    shutil.rmtree(dst)
n = 0
for it in subset:
    s = src / f"{it['id']}.drbench.md"
    if not s.exists():
        continue
    d = dst / it["subject"] / f"{it['document_id']}_page_{it['page']}-{it['page']}.md"
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(s, d)
    n += 1
print(f"{run}: {n} prediction files -> {dst}")
