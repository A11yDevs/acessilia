#!/usr/bin/env python3
"""Simulate text-pick policies per GT block on dev-986 md2md (page-level, length-weighted like the official metric).
Policies: v3a (as is) | mineru-if-both | docling-if-both | oracle | + lever A (decor tail) variants."""
import json, glob, re, statistics as st
from collections import defaultdict
ROOT = "/raid/user_marcospaulo/drdocbench"
def norm(s): return re.sub(r"\s+", "", s or "")
def load(r):
    by = defaultdict(list)
    for x in json.load(open(f"{ROOT}/runs/dev-full/official/result/{r}-w1-md2md_text_block_result.json")): by[x["img_id"]].append(x)
    return by
R = {r: load(r) for r in ["v3a-clean", "docling", "mineru"]}
cat_index = defaultdict(list)
for jp in glob.glob(f"{ROOT}/data/hf/dev/*/*/json/*_page_*.json"):
    j = json.load(open(jp)); j = j[0] if isinstance(j, list) and j else j
    if not isinstance(j, dict): continue
    pi = j["page_info"]; img = f"{pi['page_name']}_page_{pi['page_no']}-{pi['page_no']}.jpg"
    for det in j.get("layout_dets") or []:
        t = norm(det.get("text"))
        if t: cat_index[img].append((t, det.get("category_type")))
def category(img, gt):
    g = norm(gt)[:30]
    for t, c in cat_index.get(img, []):
        if g and (g in t or t[:30] in g): return c
    return "?"
def matched(x): return x is not None and x["pred_position"] != ""
def eu(x): return (x["Edit_num"], x["upper_len"])
res = defaultdict(list)
for img, S in R["v3a-clean"].items():
    idx = {r: {norm(x["gt"]): x for x in R[r].get(img, []) if x["gt_position"] != [""]} for r in R}
    extra = {r: sum(x["Edit_num"] for x in R[r].get(img, []) if x["gt_position"] == [""]) for r in R}
    tot = {p: [0, 0] for p in ["v3a", "mineru_if_both", "docling_if_both", "oracle", "v3a+A", "mineru_if_both+A", "oracle+A"]}
    for x in S:
        if x["gt_position"] == [""]: continue
        k = norm(x["gt"]); xd, xm = idx["docling"].get(k), idx["mineru"].get(k)
        c = category(img, x["gt"]); decor = c in ("header", "footer", "page_number")
        cands = [eu(y) for y in (xd, xm) if matched(y)]
        both = matched(xd) and matched(xm)
        base = eu(x)
        pol = {"v3a": base,
               "mineru_if_both": eu(xm) if both else base,
               "docling_if_both": eu(xd) if both else base,
               "oracle": min(cands + [base], key=lambda t: t[0] / t[1]) if cands else base}
        for p, v in list(pol.items()):
            va = v
            if decor and not matched(x) and matched(xd): va = eu(xd)  # lever A recovers decor via Docling
            if p + "+A" in tot: tot[p + "+A"][0] += va[0]; tot[p + "+A"][1] += va[1]
            tot[p][0] += v[0]; tot[p][1] += v[1]
    for p in tot:
        e, u = tot[p]; e += extra["v3a-clean"]; u += extra["v3a-clean"]  # extra pred blocks (edit=upper)
        if u: res[p].append(1 - e / u)
print("| policy | text (dev-986 md2md) |\n|---|---|")
for p, v in res.items(): print(f"| {p} | {100*st.mean(v):.1f} |")
