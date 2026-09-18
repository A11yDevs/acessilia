#!/usr/bin/env python3
"""Simulate levers on dev-986 md2md using the official evaluator's per-block text results.
Levers: A = decor (header/footer/page_number) emitted after body in GT order using Docling's blocks;
        O = per-block oracle text (best of v3a/docling/mineru per GT block);
        RO decomposition: loss from unmatched blocks vs misordering.
Usage: simulate_levers.py [run]  (default v3a-clean)"""
import json, glob, re, os, sys, statistics as st
from collections import defaultdict, Counter
import Levenshtein

ROOT = "/raid/user_marcospaulo/drdocbench"
run = sys.argv[1] if len(sys.argv) > 1 else "v3a-clean"
DECOR = {"header": 0, "footer": 1, "page_number": 2}

def load(r):
    d = json.load(open(f"{ROOT}/runs/dev-full/official/result/{r}-w1-md2md_text_block_result.json"))
    by = defaultdict(list)
    for x in d: by[x["img_id"]].append(x)
    return by
R = {r: load(r) for r in [run, "docling", "mineru"]}
win = {r: {w["window"]: w for w in json.load(open(f"{ROOT}/runs/dev-full/{r}/reports/official_w1-md2md.json"))["windows"]} for r in [run, "docling", "mineru"]}

def norm(s): return re.sub(r"\s+", "", s or "")
cat_index = defaultdict(list)
for jp in glob.glob(f"{ROOT}/data/hf/dev/*/*/json/*_page_*.json"):
    j = json.load(open(jp))
    if isinstance(j, list):
        if not j: continue
        j = j[0]
    pi = j["page_info"]; img = f"{pi['page_name']}_page_{pi['page_no']}-{pi['page_no']}.jpg"
    for det in j.get("layout_dets") or []:
        t = norm(det.get("text"))
        if t: cat_index[img].append((t, det.get("category_type")))
def category(img, gt):
    g = norm(gt)[:30]
    for t, c in cat_index.get(img, []):
        if g and (g in t or t[:30] in g): return c
    return "?"

def page_text(samples):
    up = sum(x.get("upper_len", max(len(x["norm_pred"]), len(x["norm_gt"]))) for x in samples)
    ed = sum(x.get("Edit_num", Levenshtein.distance(x["norm_pred"], x["norm_gt"])) for x in samples)
    return 1 - ed / up if up else None

def page_ro(samples, pos_override=None):
    matched = []; gt_all = []
    for x in samples:
        if x["gt_position"] == [""]: continue
        gt_all.extend(x["gt_position"])
        pp = (pos_override or {}).get(id(x), x["pred_position"])
        if pp != "": matched.append((x["gt_position"], pp))
    gt_sorted = sorted(p for p in gt_all if p)
    pred_flat = [p for gp, _ in sorted(matched, key=lambda t: t[1]) for p in gp if p]
    if not (gt_sorted or pred_flat): return None
    return 1 - Levenshtein.distance(gt_sorted, pred_flat) / max(len(gt_sorted), len(pred_flat), 1)

def evalai(text, ro, w):
    comps = [v for v in [text, ro] if v is not None] + [w[c] / 100 for c in ("teds", "cdm") if w.get(c) is not None]
    return st.mean(comps) if comps else None

base_t, base_ro, base_ov = [], [], []
simA_t, simA_ro, simA_ov = [], [], []
ro_matched_only = []
oracle_t = []
gain_pages = []
extra_cost = Counter()
for img, S in R[run].items():
    w = win[run].get(img, {})
    t0, ro0 = page_text(S), page_ro(S)
    if t0 is None: continue
    base_t.append(t0); base_ov.append(evalai(t0, ro0, w))
    if ro0 is not None: base_ro.append(ro0)
    # RO with only matched GT blocks (removes penalty of unmatched)
    Sm = [x for x in S if x["pred_position"] != "" or x["gt_position"] == [""]]
    rm = page_ro(Sm)
    if rm is not None and ro0 is not None: ro_matched_only.append(rm)
    # ---- lever A: unmatched decor -> take docling's match for same GT text, place at tail in GT-decor order
    D = {norm(x["gt"]): x for x in R["docling"].get(img, []) if x["gt_position"] != [""]}
    S2 = []; tail = []; maxpos = max([x["pred_position"] for x in S if x["pred_position"] != ""] + [0])
    for x in S:
        if x["pred_position"] == "" and x["gt_position"] != [""]:
            c = category(img, x["gt"])
            if c in DECOR:
                dx = D.get(norm(x["gt"]))
                if dx and dx["pred_position"] != "":
                    y = dict(x); y["norm_pred"] = dx["norm_pred"]; y["pred"] = dx["pred"]
                    y["Edit_num"] = Levenshtein.distance(y["norm_pred"], y["norm_gt"]); y["upper_len"] = max(len(y["norm_pred"]), len(y["norm_gt"]))
                    tail.append((DECOR[c], x["gt_position"][0], y)); continue
        S2.append(x)
    over = {}
    for k, (_, _, y) in enumerate(sorted(tail, key=lambda t: (t[0], t[1]))):
        over[id(y)] = maxpos + 1 + k; S2.append(y)
    t1, ro1 = page_text(S2), page_ro(S2, over)
    simA_t.append(t1); simA_ov.append(evalai(t1, ro1, w))
    if ro1 is not None: simA_ro.append(ro1)
    if tail: gain_pages.append((evalai(t1, ro1, w) - evalai(t0, ro0, w), img))
    # ---- per-block oracle text among runs (by GT text key)
    cands = [{norm(x["gt"]): x for x in R[r].get(img, []) if x["gt_position"] != [""]} for r in R]
    ed = up = 0
    for x in S:
        if x["gt_position"] == [""]: extra_cost[run] += 1; ed += x["Edit_num"]; up += x["upper_len"]; continue
        k = norm(x["gt"]); best = None
        for cd in cands:
            y = cd.get(k)
            if y and y["pred_position"] != "":
                e = Levenshtein.distance(y["norm_pred"], y["norm_gt"]); u = max(len(y["norm_pred"]), len(y["norm_gt"]))
                if best is None or e / u < best[0] / best[1]: best = (e, u)
        if best is None: best = (x["Edit_num"], x["upper_len"])
        ed += best[0]; up += best[1]
    oracle_t.append(1 - ed / up if up else t0)

pct = lambda v: f"{100*st.mean(v):.1f}"
print(f"run={run} pages={len(base_t)}")
print(f"| metric | baseline | lever A (decor tail via Docling) | per-block text oracle |\n|---|---|---|---|")
print(f"| text | {pct(base_t)} | {pct(simA_t)} | {pct(oracle_t)} |")
print(f"| RO | {pct(base_ro)} | {pct(simA_ro)} | RO matched-only (no unmatched penalty): {pct(ro_matched_only)} |")
print(f"| evalai_style | {pct(base_ov)} | {pct(simA_ov)} | – |")
gain_pages.sort()
print(f"pages touched by A: {len(gain_pages)}; hurt (<-1): {sum(1 for g,_ in gain_pages if g < -0.01)}; helped (>+1): {sum(1 for g,_ in gain_pages if g > 0.01)}")
print("worst 5 by A:", [(round(100*g,1), i[:8], i.split('_page_')[1].split('-')[0]) for g, i in gain_pages[:5]])
print("best 5 by A:", [(round(100*g,1), i[:8], i.split('_page_')[1].split('-')[0]) for g, i in gain_pages[-5:]])
