#!/usr/bin/env python3
"""Classify unmatched GT text blocks (pred=='') of a md2md run by GT JSON category. Usage: unmatched_by_category.py RUN"""
import json, glob, re, os, sys
from collections import Counter, defaultdict
ROOT = "/raid/user_marcospaulo/drdocbench"
run = sys.argv[1] if len(sys.argv) > 1 else "v3a-clean"
d = json.load(open(f"{ROOT}/runs/dev-full/official/result/{run}-w1-md2md_text_block_result.json"))
def norm(s): return re.sub(r"\s+", "", s or "")
# index GT json blocks by page
cat_index = defaultdict(list)
for jp in glob.glob(f"{ROOT}/data/hf/dev/*/*/json/*_page_*.json"):
    j = json.load(open(jp))
    if isinstance(j, list):
        if not j: continue
        j = j[0]
    pi = j["page_info"]; img = f"{pi['page_name']}_page_{pi['page_no']}-{pi['page_no']}.jpg"
    for det in j.get("layout_dets") or []:
        t = norm(det.get("text"))
        if t: cat_index[img].append((t, det.get("category_type"), det.get("attribute", {}).get("text_rotate")))
def category(x):
    g = norm(x["gt"]); g30 = g[:30]
    for t, c, rot in cat_index.get(x["img_id"], []):
        if g30 and (g30 in t or t[:30] in g): return c, rot
    return "?", None
tot = Counter(); un = Counter(); un_rot = Counter(); edit_mass = Counter()
for x in d:
    c, rot = category(x)
    tot[c] += 1; edit_mass[c] += x["edit"]
    if x["pred"] == "":
        un[c] += 1
        if rot and rot != "normal": un_rot[c] += 1
print(f"run={run}  blocks={len(d)}  unmatched={sum(un.values())}  total edit mass={sum(edit_mass.values()):.0f}")
print("| category | GT blocks | unmatched | % unmatched | edit mass | unmatched rotated |\n|---|---|---|---|---|---|")
for c, n in tot.most_common():
    print(f"| {c} | {n} | {un[c]} | {100*un[c]/n:.0f}% | {edit_mass[c]:.0f} | {un_rot[c]} |")
