#!/usr/bin/env python3
"""Per-GT-block comparison docling vs mineru (both matched) on dev-986 md2md: who wins, by category and by edit gap."""
import json, glob, re, statistics as st
from collections import defaultdict, Counter
ROOT = "/raid/user_marcospaulo/drdocbench"
def norm(s): return re.sub(r"\s+", "", s or "")
def load(r):
    by = defaultdict(dict)
    for x in json.load(open(f"{ROOT}/runs/dev-full/official/result/{r}-w1-md2md_text_block_result.json")):
        if x["gt_position"] != [""]: by[x["img_id"]][norm(x["gt"])] = x
    return by
D, M, V = load("docling"), load("mineru"), load("v3a-clean")
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
def ed(x): return x["Edit_num"] / x["upper_len"] if x["upper_len"] else 0
wins = Counter(); mass = Counter(); n = Counter(); v_choice = Counter()
gap_hist = Counter()
seg = Counter()
for img in V:
    for k, xv in V[img].items():
        xd, xm = D.get(img, {}).get(k), M.get(img, {}).get(k)
        c = category(img, xv["gt"]); grp = "body" if c in ("text_block", "title", "?") else "decor/caption"
        n[grp] += 1
        bd = xd is not None and xd["pred_position"] != ""; bm = xm is not None and xm["pred_position"] != ""
        if bd and bm:
            e_d, e_m = ed(xd), ed(xm); e_v = ed(xv)
            w = "tie" if abs(e_d - e_m) < 0.02 else ("docling" if e_d < e_m else "mineru")
            wins[(grp, w)] += 1
            mass[(grp, "docling_better_by")] += max(0, e_m - e_d) * xv["upper_len"]
            mass[(grp, "mineru_better_by")] += max(0, e_d - e_m) * xv["upper_len"]
            mass[(grp, "upper")] += xv["upper_len"]
            # what did v3a end up with?
            v_choice[(grp, "v3a=best" if e_v <= min(e_d, e_m) + 0.02 else ("v3a=worse_than_best"))] += 1
            if w != "tie": gap_hist[(w, round(abs(e_d - e_m), 1))] += 1
            # segmentation: pred longer/shorter than gt by provider
            for name, x in (("docling", xd), ("mineru", xm)):
                lg, lp = len(x["norm_gt"]), len(x["norm_pred"])
                seg[(name, "merge" if lp > 1.5 * lg else "split" if lg > 1.5 * lp else "ok")] += 1
        elif bd and not bm: wins[(grp, "only_docling")] += 1
        elif bm and not bd: wins[(grp, "only_mineru")] += 1
        else: wins[(grp, "neither")] += 1
print("| group | n GT blocks | docling wins | mineru wins | tie | only docling | only mineru | neither |\n|---|---|---|---|---|---|---|---|")
for g in ("body", "decor/caption"):
    print(f"| {g} | {n[g]} | {wins[(g,'docling')]} | {wins[(g,'mineru')]} | {wins[(g,'tie')]} | {wins[(g,'only_docling')]} | {wins[(g,'only_mineru')]} | {wins[(g,'neither')]} |")
print("\nlength-weighted advantage on blocks matched by both (edit-mass, as % of those blocks' chars):")
for g in ("body", "decor/caption"):
    u = mass[(g, "upper")] or 1
    print(f"  {g}: docling better by {100*mass[(g,'docling_better_by')]/u:.2f}% | mineru better by {100*mass[(g,'mineru_better_by')]/u:.2f}%")
print("\nv3a choice quality on both-matched blocks:", dict(v_choice))
print("\nsegmentation vs GT (both-matched blocks):", {k: v for k, v in sorted(seg.items())})
print("\ngap histogram (winner, |Δedit|):", sorted(gap_hist.items(), key=lambda t: (t[0][0], t[0][1])))
