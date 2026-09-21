#!/usr/bin/env python3
"""In curated GT md, are header/footer/page_number appended after the body? In which order among them?"""
import json, glob, re, os
from collections import Counter
ROOT = "/raid/user_marcospaulo/drdocbench/data/hf/dev"
DECOR = ("page_number", "header", "footer")
after_body = Counter(); order_pairs = Counter(); n_pages = 0
def norm(s): return re.sub(r"\s+", "", s)
for jp in glob.glob(f"{ROOT}/*/*/json/*_page_*.json"):
    j = json.load(open(jp))
    if isinstance(j, list):
        if not j: continue
        j = j[0]
    dets = j.get("layout_dets") or []
    uuid = j["page_info"]["page_name"]; pn = j["page_info"]["page_no"]
    mdp = f"{os.path.dirname(os.path.dirname(jp))}/mds/{uuid}_{pn}.md"
    if not os.path.exists(mdp): continue
    lines = [norm(l) for l in open(mdp).read().split("\n") if l.strip() and not l.startswith("![")]
    if not lines: continue
    def find(t):
        k = norm(t)[:30]
        for i, l in enumerate(lines):
            if k and k in l: return i
        return None
    decor = {}; body_idx = []
    for d in dets:
        c = d.get("category_type"); t = (d.get("text") or "").strip()
        if not t or c in ("figure", "table", "equation_isolated", "text_mask"): continue
        i = find(t)
        if i is None: continue
        if c in DECOR: decor.setdefault(c, []).append(i)
        else: body_idx.append(i)
    if not decor: continue
    n_pages += 1
    last_body = max(body_idx) if body_idx else -1
    for c, idxs in decor.items():
        for i in idxs: after_body[(c, "after_body" if i > last_body else "inside_body")] += 1
    # relative order among decor categories
    firsts = {c: min(v) for c, v in decor.items()}
    for a in firsts:
        for b in firsts:
            if a < b: order_pairs[(a, b, "a<b" if firsts[a] < firsts[b] else "b<a")] += 1
print("pages with decor:", n_pages)
for k in sorted(after_body): print(k, after_body[k])
print("--- relative order")
for k in sorted(order_pairs): print(k, order_pairs[k])
