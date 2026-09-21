#!/usr/bin/env python3
"""Text edit-mass taxonomy (length-weighted, as the official page metric) for a md2md run."""
import json, glob, re, sys, statistics as st
from collections import defaultdict, Counter
ROOT = "/raid/user_marcospaulo/drdocbench"
run = sys.argv[1] if len(sys.argv) > 1 else "v3a-clean"
d = json.load(open(f"{ROOT}/runs/dev-full/official/result/{run}-w1-md2md_text_block_result.json"))
subj = {p.split("/")[-1]: p.split("/")[-2] for p in glob.glob(f"{ROOT}/data/hf/dev/*/*")}
def norm(s): return re.sub(r"\s+", "", s or "")
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

# page-level weights: the page score is 1 - sum(edit)/sum(upper); overall = mean over pages.
# contribution of block b to page loss = Edit_num_b / sum_upper_page; to overall loss = that / n_pages
pages = defaultdict(list)
for x in d: pages[x["img_id"]].append(x)
n_pages = len(pages)
loss = Counter(); examples = defaultdict(list)
def classify(x):
    g, p = x["norm_gt"], x["norm_pred"]
    if x["gt_position"] == [""]: return "extra_pred"
    if x["pred_position"] == "":
        c = category(x["img_id"], x["gt"])
        return f"unmatched_gt:{c if c in ('header','footer','page_number','title') else 'body'}"
    e = x["Edit_num"] / x["upper_len"]
    lg, lp = len(g), len(p)
    if e <= 0.02: return "matched:near_perfect"
    if e <= 0.15: return "matched:ocr_small"
    if lp > 1.5 * lg: return "matched:pred_longer(merge)"
    if lg > 1.5 * lp: return "matched:pred_shorter(split/trunc)"
    if e > 0.6: return "matched:wrong_pair"
    return "matched:ocr_heavy"
for img, S in pages.items():
    up = sum(x["upper_len"] for x in S)
    if not up: continue
    for x in S:
        k = classify(x); v = x["Edit_num"] / up / n_pages * 100
        loss[k] += v
        if len(examples[k]) < 4 and x["Edit_num"] / up > 0.05: examples[k].append((img[:8], img.split("_page_")[1].split("-")[0], subj.get(img.split("_page_")[0]), x["gt"][:70].replace("\n", "⏎"), x["pred"][:70].replace("\n", "⏎")))
tot = sum(loss.values())
print(f"run={run}  text score = {100 - tot:.1f}  (loss {tot:.1f} pts)")
print("| bucket | loss (pts of text score) | share |\n|---|---|---|")
for k, v in loss.most_common(): print(f"| {k} | {v:.2f} | {100*v/tot:.0f}% |")
for k, ex in examples.items():
    print(f"\n### {k}")
    for e in ex: print("  ", e)
