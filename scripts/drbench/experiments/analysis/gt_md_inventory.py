#!/usr/bin/env python3
"""Does the curated GT markdown (mds/) include page numbers, headers, footers, captions? Where?"""
import json, glob, re, os
from collections import Counter
ROOT = "/raid/user_marcospaulo/drdocbench/data/hf/dev"
stats = Counter(); pos = Counter(); ex = []
for jp in glob.glob(f"{ROOT}/*/*/json/*_page_*.json"):
    j = json.load(open(jp))
    if isinstance(j, list):
        if not j: continue
        j = j[0]
    dets = j.get("layout_dets") or []
    uuid = j["page_info"]["page_name"]; pn = j["page_info"]["page_no"]
    mdp = f"{os.path.dirname(os.path.dirname(jp))}/mds/{uuid}_{pn}.md"
    if not os.path.exists(mdp): stats["no_md"] += 1; continue
    md = open(mdp).read()
    lines = [l.strip() for l in md.split("\n") if l.strip() and not l.startswith("![")]
    for d in dets:
        c = d.get("category_type")
        if c in ("page_number", "header", "footer", "figure_caption", "table_caption", "footnote", "page_footnote", "table_footnote"):
            t = (d.get("text") or "").strip()
            if not t: stats[(c, "notext")] += 1; continue
            key = re.sub(r"\s+", "", t)[:30]
            hits = [i for i, l in enumerate(lines) if key and key in re.sub(r"\s+", "", l)]
            stats[(c, "in_md" if hits else "absent")] += 1
            if hits:
                idx = hits[0]
                pos[(c, "first" if idx == 0 else ("last" if idx == len(lines) - 1 else "middle"))] += 1
                if c in ("header", "footer") and len(ex) < 6: ex.append((mdp.split("/")[-1], c, t[:50]))
for k in sorted(stats, key=str): print(k, stats[k])
print("--- position when in md")
for k in sorted(pos): print(k, pos[k])
print(ex)
