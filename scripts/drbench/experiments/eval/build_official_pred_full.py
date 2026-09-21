#!/usr/bin/env python
"""Build the DrDocBench multipage-evaluator prediction tree for a full split.

Pages are enumerated from the GT tree (gt_root/<subject>/<doc>/json/<doc>_page_N.json).
--window 1   -> one file per page       <doc>_page_N-N.md
--window doc -> one file per contiguous page run of a document  <doc>_page_S-E.md
                (pages concatenated in ascending order, separated by a blank line;
                 a missing prediction contributes an empty page).
"""
import argparse
import re
import shutil
from collections import defaultdict
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--predictions", type=Path, required=True, help="dir with <doc>_p<N>.drbench.md")
ap.add_argument("--gt-root", type=Path, required=True)
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--window", choices=["1", "doc"], default="1")
a = ap.parse_args()

pages = defaultdict(list)  # (subject, doc) -> [page]
for p in a.gt_root.glob("*/*/json/*_page_*.json"):
    m = re.search(r"_page_(\d+)\.json$", p.name)
    pages[(p.parts[-4], p.parts[-3])].append(int(m.group(1)))

if a.out.exists():
    shutil.rmtree(a.out)
n_files = n_pages = n_missing = 0
for (subject, doc), nums in sorted(pages.items()):
    nums = sorted(nums)
    if a.window == "1":
        segments = [[n] for n in nums]
    else:
        segments, cur = [], [nums[0]]
        for n in nums[1:]:
            if n == cur[-1] + 1:
                cur.append(n)
            else:
                segments.append(cur)
                cur = [n]
        segments.append(cur)
    for seg in segments:
        parts = []
        for n in seg:
            src = a.predictions / f"{doc}_p{n}.drbench.md"
            if src.exists():
                parts.append(src.read_text(encoding="utf-8").strip())
            else:
                parts.append("")
                n_missing += 1
            n_pages += 1
        dst = a.out / subject / f"{doc}_page_{seg[0]}-{seg[-1]}.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
        n_files += 1
print(f"window={a.window}: {n_files} prediction files, {n_pages} pages ({n_missing} missing preds) -> {a.out}")
