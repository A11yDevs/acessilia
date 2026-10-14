#!/usr/bin/env python
"""Fast replica of the official md2md text + reading_order scoring (no TEDS) for 1-page windows.
usage: fastscore.py PRED_DIR [--out per_page.json] [--dump DIR]   (PRED_DIR has <doc>_p<N>.drbench.md)
Prints tune/hold/all means of text and RO (x100)."""
import sys, os, re, json, glob, hashlib, argparse
from multiprocessing import Pool
WS = os.environ.get("DRBENCH_WS", "/raid/user_marcospaulo/drdocbench")
REPO = os.environ.get("DRBENCH_EVALUATOR", f"{WS}/repos/DrDocBench")
sys.path.insert(0, REPO); os.chdir(REPO)
import Levenshtein
from utils.extract import md_tex_filter
from utils.match_quick import match_gt2pred_quick
from dataset.multipage_md2md_dataset import MultipageMd2MdDataset
GT = os.environ.get("DRBENCH_GT", f"{WS}/data/hf/dev")

def pages():
    out = []
    for p in glob.glob(f"{GT}/*/*/json/*_page_*.json"):
        subj, doc = p.split("/")[-4], p.split("/")[-3]
        if subj == "MUSIC":
            continue
        n = int(re.search(r"_page_(\d+)\.json$", p).group(1))
        g = f"{GT}/{subj}/{doc}/mds/{doc}_{n}.md"
        if os.path.exists(g):
            out.append((subj, doc, n))
    return sorted(out)

def score_page(args):
    pred_dir, subj, doc, n = args
    gt = open(f"{GT}/{subj}/{doc}/mds/{doc}_{n}.md", encoding="utf-8").read()
    pf = f"{pred_dir}/{doc}_p{n}.drbench.md"
    pred = (open(pf, encoding="utf-8").read().strip() if os.path.exists(pf) else "") + "\n"
    win = f"{doc}_page_{n}-{n}.jpg"
    if not gt.strip():
        return win, None, None, []
    g, p = md_tex_filter(gt), md_tex_filter(pred)
    text = ro = None; m = []
    if g.get("text_all"):
        m = match_gt2pred_quick(g["text_all"], p.get("text_all", []), "text", win, skip_truncated=True)
        num = den = 0
        for s in m:
            a = s["norm_gt"] if s.get("norm_gt") else s["gt"]
            b = s["norm_pred"] if s.get("norm_pred") else s["pred"]
            if a or b:
                num += Levenshtein.distance(b, a); den += max(len(a), len(b))
        text = 100 * (1 - num / den) if den else None
        o = MultipageMd2MdDataset._get_order_paired(None, m, win)
        ro = 100 * (1 - o["edit"]) if o else None
    return win, text, ro, [(s.get("norm_gt", ""), s.get("norm_pred", "")) for s in m]

def part(win):
    return "hold" if int(hashlib.md5(win.split("_page_")[0].encode()).hexdigest(), 16) % 3 == 0 else "tune"

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("pred"); ap.add_argument("--out"); ap.add_argument("--pairs")
    a = ap.parse_args()
    R = WS.rstrip("/") + "/"
    a.out = a.out and os.path.join(R, a.out); a.pairs = a.pairs and os.path.join(R, a.pairs)
    pd = os.path.abspath(os.path.join(WS, a.pred))
    with Pool(24) as pool:
        res = pool.map(score_page, [(pd, *x) for x in pages()], chunksize=4)
    rows = {w: {"text": t, "reading_order": r} for w, t, r, _ in res}
    for sub in ("tune", "hold", "all"):
        tv = [v["text"] for k, v in rows.items() if v["text"] is not None and (sub == "all" or part(k) == sub)]
        rv = [v["reading_order"] for k, v in rows.items() if v["reading_order"] is not None and (sub == "all" or part(k) == sub)]
        print(f"{sub}: text={sum(tv)/len(tv):.3f} (n={len(tv)}) RO={sum(rv)/len(rv):.3f} (n={len(rv)}) mean2={(sum(tv)/len(tv)+sum(rv)/len(rv))/2:.3f}")
    if a.out:
        json.dump(rows, open(a.out, "w"))
    if a.pairs:
        json.dump({w: p for w, _, _, p in res}, open(a.pairs, "w"))
