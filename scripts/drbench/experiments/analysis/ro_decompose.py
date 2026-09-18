#!/usr/bin/env python3
"""Decompose reading-order loss of a md2md run: full RO vs matched-only vs matched-only-excluding-decor (page_number/header/footer).
Usage: repos/DrDocBench/.venv/bin/python scripts/ro_decompose.py RUN"""
import json, glob, re, sys, statistics as st
from collections import defaultdict
import Levenshtein
ROOT = "/raid/user_marcospaulo/drdocbench"
run = sys.argv[1] if len(sys.argv) > 1 else "v3a-clean"
DECOR = {"page_number", "header", "footer"}
def norm(s): return re.sub(r"\s+", "", s or "")
cat_index = defaultdict(list); lay = {}
for jp in glob.glob(f"{ROOT}/data/hf/dev/*/*/json/*_page_*.json"):
    j = json.load(open(jp)); j = j[0] if isinstance(j, list) and j else j
    if not isinstance(j, dict): continue
    pi = j["page_info"]; img = f"{pi['page_name']}_page_{pi['page_no']}-{pi['page_no']}.jpg"
    lay[img] = pi.get("page_attribute", {}).get("layout")
    for det in j.get("layout_dets") or []:
        t = norm(det.get("text"))
        if t: cat_index[img].append((t, det.get("category_type")))
def category(x):
    g = norm(x["gt"]); g30 = g[:30]
    for t, c in cat_index.get(x["img_id"], []):
        if g30 and (g30 in t or t[:30] in g): return c
    return "?"
def ro(S, only_matched=False, drop_decor=False):
    m = []; g = []
    for x in S:
        if x["gt_position"] == [""]: continue
        if only_matched and x["pred_position"] == "": continue
        if drop_decor and category(x) in DECOR: continue
        g.extend(x["gt_position"])
        if x["pred_position"] != "": m.append((x["gt_position"], x["pred_position"]))
    gs = sorted(p for p in g if p); pf = [p for gp, _ in sorted(m, key=lambda t: t[1]) for p in gp if p]
    if not (gs or pf): return None
    return 1 - Levenshtein.distance(gs, pf) / max(len(gs), len(pf), 1)
by = defaultdict(list)
for x in json.load(open(f"{ROOT}/runs/dev-full/official/result/{run}-w1-md2md_text_block_result.json")): by[x["img_id"]].append(x)
rows = []
for img, S in by.items():
    a, b, c = ro(S), ro(S, True), ro(S, True, True)
    if None in (a, b, c): continue
    rows.append((img, a, b, c))
print(f"run={run} pages={len(rows)}")
print(f"RO full            {100*st.mean(r[1] for r in rows):.1f}")
print(f"RO matched-only    {100*st.mean(r[2] for r in rows):.1f}  (gap = unmatched GT blocks)")
print(f"RO matched, nodecor{100*st.mean(r[3] for r in rows):.1f}  (gap = decor misplaced)")
bl = defaultdict(list)
for img, a, b, c in rows: bl[lay.get(img)].append(c)
print("matched+nodecor by layout:", {k: (round(100*st.mean(v), 1), len(v)) for k, v in bl.items()})
worst = sorted(rows, key=lambda r: r[3])[:15]
print("worst pages (matched, nodecor):")
for img, a, b, c in worst: print(f"  {img} full={100*a:.0f} matched={100*b:.0f} nodecor={100*c:.0f} layout={lay.get(img)}")
