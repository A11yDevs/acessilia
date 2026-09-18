#!/usr/bin/env python
"""Aggregate local per-page reports into Tables 2-4, strata, oracle, delta,
duplication / agreement / formula analyses and worst pages -> summary.md.

Usage (any python3 with numpy):
  python scripts/eval_summary.py --runs docling docling-forceocr mineru \
      --primary docling-forceocr --secondary mineru
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np

WS = Path(__file__).resolve().parents[1]
DEV = WS / "runs" / "dev"
class _Label(dict):
    def __missing__(self, k):
        return k


LABEL = _Label({"docling": "Docling (default)", "docling-forceocr": "Docling (force OCR)",
                "mineru": "MinerU", "adjudicator-v0": "Adjudicator v0",
                "adjudicator-v0b": "Adjudicator v0b (agreement)"})
STRATA = ["plain", "multicol", "special", "table", "equation"]
COMPS = [("overall", "Overall"), ("text", "Text (1-Edit)×100"),
         ("reading_order", "Reading order"), ("teds", "TEDS"), ("cdm", "CDM (token-F1)")]


MANUAL_HYP = {
    "a5cc5b38-7122-404b-93e7-1472fb3e8e74_p145": "figure-only page (GT = image ref); Docling OCRs the word 'STYLIST' inside the figure",
    "11fb213b-fe17-4bde-9f32-85010907118d_p78": "whole page is one wireless horizontal table; Docling pipeline drops table content, only page number/footer survive",
    "f8438f43-c0d7-4dae-8497-16f1d222e9b2_p226": "boxing-record list rendered as tables in GT; Docling output empty (tables flattened away)",
    "f8438f43-c0d7-4dae-8497-16f1d222e9b2_p224": "same document/pattern as p226: tabular record pages -> empty Docling output",
    "f8438f43-c0d7-4dae-8497-16f1d222e9b2_p222": "same document/pattern as p226",
    "f8438f43-c0d7-4dae-8497-16f1d222e9b2_p225": "same document/pattern as p226",
    "18b6da40-f4c6-49c5-9725-dec8cbde2c4a_p355": "fuzzy-scan advertisement page; MinerU layout detects only figures -> empty output",
    "11fb213b-fe17-4bde-9f32-85010907118d_p79": "wireless 2-column table collapsed by MinerU into a single 1x2 cell (structure lost, TEDS 0)",
    "23bdb6d7-c5ef-4c2a-971b-fbf1f6d0f9ca_p120": "fuzzy scan, multi-column; MinerU returns almost nothing",
    "d824013e-80a3-4149-877e-a60274be2fc7_p36": "comic-style page, text inside colored artwork; MinerU treats page as a figure",
    "547e2947-5211-4ccf-83ae-f9dbf47a491f_p21": "colorful background; MinerU misses most text regions",
}


def load(run):
    rows = json.loads((DEV / run / "reports" / "local_pages.json").read_text())
    return {r["id"]: r for r in rows}


def mean(vals):
    vals = [v for v in vals if v is not None]
    return (float(np.mean(vals)) if vals else None), len(vals)


def fmt(v, nd=1):
    return "–" if v is None else f"{v:.{nd}f}"


def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    # average ranks for ties
    for arr, r in ((x, rx), (y, ry)):
        for v in np.unique(arr):
            m = arr == v
            r[m] = r[m].mean()
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def norm_text(md):
    md = re.sub(r"<[^>]+>", " ", md)
    md = re.sub(r"[#*_`|>$\\\[\]{}]", " ", md)
    return re.sub(r"\s+", " ", md).strip().lower()


def dup_rate(md):
    """Repeated prose line (>=40 chars, no HTML) or in-line 'X X' repetition (heading bug)."""
    lines = [l.strip() for l in md.splitlines() if l.strip()]
    prose = [l for l in lines if len(l) >= 40 and "<" not in l]
    if any(v >= 2 for v in Counter(prose).values()):
        return True
    for l in lines:
        l = l.lstrip("# ").strip()
        h = len(l) // 2
        if len(l) >= 12 and len(l) % 2 == 1 and l[:h] == l[h + 1:]:
            return True
    return False


def near_empty(md):
    return len(md.replace("# Dr.DocBench page", "").strip()) < 100


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def tex_table(header, rows, caption, label, colspec=None):
    colspec = colspec or ("l" + "r" * (len(header) - 1))
    lines = [r"\begin{table}[t]", r"\centering", r"\small",
             rf"\begin{{tabular}}{{{colspec}}}", r"\toprule",
             " & ".join(header) + r" \\", r"\midrule"]
    lines += [" & ".join(str(c) for c in r) + r" \\" for r in rows]
    lines += [r"\bottomrule", r"\end{tabular}", rf"\caption{{{caption}}}",
              rf"\label{{{label}}}", r"\end{table}"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--primary", default="docling-forceocr")
    ap.add_argument("--secondary", default="mineru")
    ap.add_argument("--out", type=Path, default=DEV / "summary.md")
    a = ap.parse_args()

    subset = {it["id"]: it for it in json.loads((DEV / "subset.json").read_text())}
    data = {r: load(r) for r in a.runs}
    ids = sorted(set.intersection(*(set(d) for d in data.values())))
    ids = [i for i in ids if i in subset]
    N = len(ids)
    out = {"n_pages_common": N, "runs": a.runs}
    md = []
    tex = []

    md.append(f"# Dev-subset evaluation summary (local, approximate metrics)\n")
    md.append(f"Generated by `scripts/eval_summary.py` from `runs/dev/<run>/reports/local_pages.json`.\n")
    md.append("**Methodology.** Local metrics reuse acessilia `scripts/metrics` (normalized Levenshtein for text and "
              "reading order; simplified Zhang–Shasha TEDS over `<table>` HTML; CDM approximated as LaTeX token-F1). "
              "TEDS/CDM are scored only on pages whose GT Markdown contains a `<table>` / `$$…$$` block; a prediction "
              "without that component scores 0 (EvalAI semantics). Overall = per-page mean of available components. "
              "These are **local (approximate)** numbers, not the official DrDocBench evaluator. Caveats: local text/RO compare the raw "
              "whole-page Markdown (including the GT `![](imgs/…)` figure references and the `# Dr.DocBench page` header emitted by the pipeline), "
              "so they are systematically lower than the official block-matched Edit distance; see the OFFICIAL section at the end.\n")

    # strata counts
    sc = Counter(s for i in ids for s in subset[i]["strata"])
    md.append("## Subset\n")
    md.append(f"N = {N} pages (common to all runs). Strata (multi-label): "
              + ", ".join(f"{s}={sc[s]}" for s in STRATA) + ". "
              f"Pages with GT `<table>`: {sum(1 for i in ids if data[a.runs[0]][i]['n_gt_tables'])}; "
              f"with GT display formula: {sum(1 for i in ids if data[a.runs[0]][i]['n_gt_formulas'])}.\n")
    out["strata_counts"] = dict(sc)

    # ---------- Table 2 ----------
    t2 = {}
    header = ["Metric", "N"] + [LABEL[r] for r in a.runs]
    rows = []
    for key, name in COMPS:
        vals = {r: mean([data[r][i][key] for i in ids]) for r in a.runs}
        n = vals[a.runs[0]][1]
        rows.append([name, n] + [fmt(vals[r][0]) for r in a.runs])
        t2[key] = {"n": n, **{r: vals[r][0] for r in a.runs}}
    out["table2"] = t2
    md.append("## Table 2 — Overall and components × run (local)\n")
    md.append(md_table(header, rows) + "\n")
    tex.append(("Table 2", tex_table(header, rows,
        f"Local (approximate) Dr.DocBench metrics on the stratified dev subset (N={N} pages). "
        "TEDS/CDM computed on the N pages whose ground truth contains the component; higher is better.",
        "tab:main")))

    # ---------- Table 3 ----------
    header = ["Stratum", "N"] + [LABEL[r] for r in a.runs]
    rows = []
    t3 = {}
    for s in STRATA:
        sid = [i for i in ids if s in subset[i]["strata"]]
        vals = {r: mean([data[r][i]["overall"] for i in sid])[0] for r in a.runs}
        rows.append([s, len(sid)] + [fmt(vals[r]) for r in a.runs])
        t3[s] = {"n": len(sid), **vals}
    # layout / special_issue breakdown
    for key, title in (("layout", "layout"), ("special_issue", "special_issue")):
        groups = Counter()
        for i in ids:
            v = subset[i][key]
            for g in (v if isinstance(v, list) else [v]) or ["none"]:
                groups[g] += 1
        for g, n in sorted(groups.items(), key=lambda kv: -kv[1]):
            sid = [i for i in ids if g in ((subset[i][key] if isinstance(subset[i][key], list) else [subset[i][key]]) or ["none"])]
            vals = {r: mean([data[r][i]["overall"] for i in sid])[0] for r in a.runs}
            rows.append([f"{title}={g}", n] + [fmt(vals[r]) for r in a.runs])
            t3[f"{title}={g}"] = {"n": n, **vals}
    out["table3"] = t3
    md.append("## Table 3 — Overall by stratum / layout / special_issue × run (local)\n")
    md.append(md_table(header, rows) + "\n")
    tex.append(("Table 3", tex_table(header, rows[:len(STRATA)],
        "Local overall score by stratum (multi-label; a page can belong to several strata).", "tab:strata")))

    # ---------- Table 4: oracle ----------
    P, S = a.primary, a.secondary
    po = np.array([data[P][i]["overall"] for i in ids])
    so = np.array([data[S][i]["overall"] for i in ids])
    oracle = np.maximum(po, so)
    delta = po - so
    best_single = max(po.mean(), so.mean())
    wins_p = int((delta >= 0.5).sum()); wins_s = int((delta <= -0.5).sum()); ties = int((np.abs(delta) < 0.5).sum())
    t4 = {"primary": P, "secondary": S, "n": N,
          "mean_primary": float(po.mean()), "mean_secondary": float(so.mean()),
          "oracle": float(oracle.mean()), "gain_vs_best_single": float(oracle.mean() - best_single),
          "wins_primary": wins_p, "wins_secondary": wins_s, "ties_abs_lt_0.5": ties,
          "delta_stats": {"min": float(delta.min()), "q1": float(np.percentile(delta, 25)),
                          "median": float(np.median(delta)), "q3": float(np.percentile(delta, 75)),
                          "max": float(delta.max()), "mean": float(delta.mean()), "std": float(delta.std())}}
    # oracle per component too
    comp_oracle = {}
    for key, _ in COMPS[1:]:
        pv = [(data[P][i][key], data[S][i][key]) for i in ids]
        pv = [(x, y) for x, y in pv if x is not None and y is not None]
        if pv:
            comp_oracle[key] = {"n": len(pv), P: float(np.mean([x for x, _ in pv])),
                                S: float(np.mean([y for _, y in pv])),
                                "oracle": float(np.mean([max(x, y) for x, y in pv]))}
    t4["per_component"] = comp_oracle
    out["table4"] = t4
    header = ["System", "N", "Overall (local)"]
    rows = [[LABEL[P], N, fmt(po.mean())], [LABEL[S], N, fmt(so.mean())],
            ["Per-page oracle (max)", N, fmt(oracle.mean())],
            ["Gain vs. best single", N, f"+{oracle.mean()-best_single:.1f}"],
            [f"Pages won by {LABEL[P]} / {LABEL[S]} / tie (|Δ|<0.5)", N, f"{wins_p} / {wins_s} / {ties}"]]
    md.append("## Table 4 — Per-page oracle (local)\n")
    md.append(md_table(header, rows) + "\n")
    md.append(f"Δ = overall({P}) − overall({S}): min {delta.min():.1f}, Q1 {np.percentile(delta,25):.1f}, "
              f"median {np.median(delta):.1f}, Q3 {np.percentile(delta,75):.1f}, max {delta.max():.1f} "
              f"(mean {delta.mean():.1f}, sd {delta.std():.1f}). CSV: `runs/dev/delta_per_page.csv`.\n")
    md.append("Per-component oracle (pages where both runs are scorable):\n")
    md.append(md_table(["Component", "N", LABEL[P], LABEL[S], "Oracle"],
                       [[k, v["n"], fmt(v[P]), fmt(v[S]), fmt(v["oracle"])] for k, v in comp_oracle.items()]) + "\n")
    tex.append(("Table 4", tex_table(header, rows,
        f"Per-page oracle selection between {LABEL[P]} and {LABEL[S]} (local overall, N={N}).", "tab:oracle",
        colspec="lrr")))
    with open(DEV / "delta_per_page.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "strata", f"overall_{P}", f"overall_{S}", "delta", "oracle"])
        for i, x, y in zip(ids, po, so):
            w.writerow([i, "|".join(subset[i]["strata"]), f"{x:.2f}", f"{y:.2f}", f"{x-y:.2f}", f"{max(x,y):.2f}"])

    # ---------- Analyses ----------
    md.append("## Analyses\n")
    an = {}
    # near-empty predictions
    ne = {r: [i for i in ids if near_empty((DEV / r / "predictions" / f"{i}.drbench.md").read_text())] for r in a.runs}
    an["near_empty"] = {r: {"n": len(v), "with_gt_table": sum(1 for i in v if data[r][i]["n_gt_tables"]), "ids": v} for r, v in ne.items()}
    md.append("**Near-empty predictions** (<100 chars after the page header): "
              + "; ".join(f"{LABEL[r]} {len(v)}/{N} (of which {an['near_empty'][r]['with_gt_table']} have a GT table)" for r, v in ne.items()) + ".\n")
    # (a) duplication
    if "docling" in data and "docling-forceocr" in data:
        d_dup = [dup_rate((DEV / "docling/predictions" / f"{i}.drbench.md").read_text()) for i in ids]
        f_dup = [dup_rate((DEV / "docling-forceocr/predictions" / f"{i}.drbench.md").read_text()) for i in ids]
        m_dup = [dup_rate((DEV / "mineru/predictions" / f"{i}.drbench.md").read_text()) for i in ids] if "mineru" in data else []
        gt_dup = [dup_rate(Path(subset[i]["md_path"]).read_text()) for i in ids]
        dt = np.array([data["docling-forceocr"][i]["text"] - data["docling"][i]["text"] for i in ids])
        do = np.array([data["docling-forceocr"][i]["overall"] - data["docling"][i]["overall"] for i in ids])
        an["a_duplication"] = {"docling_default_dup_frac": float(np.mean(d_dup)), "docling_forceocr_dup_frac": float(np.mean(f_dup)),
                               "mineru_dup_frac": float(np.mean(m_dup)) if m_dup else None, "gt_dup_frac": float(np.mean(gt_dup)),
                               "mean_gain_text": float(dt.mean()), "mean_gain_overall": float(do.mean()),
                               "pages_forceocr_better_overall": int((do > 0).sum()), "pages_default_better_overall": int((do < 0).sum())}
        md.append(f"**(a) Duplication.** Heuristic: a page is 'duplicated' if a prose line (≥40 chars, no HTML) appears ≥2 times "
                  "or a line/heading is an exact in-line repetition ('X X', e.g. 'CONVERSION TABLES CONVERSION TABLES'). "
                  f"Docling default: {100*np.mean(d_dup):.1f}% of pages ({sum(d_dup)}/{N}); Docling force-OCR: {100*np.mean(f_dup):.1f}% ({sum(f_dup)}/{N}); "
                  f"MinerU: {100*np.mean(m_dup):.1f}%; GT: {100*np.mean(gt_dup):.1f}%. "
                  f"Force-OCR vs default: mean gain text {dt.mean():+.1f}, overall {do.mean():+.1f} points; "
                  f"force-OCR better on {(do>0).sum()} pages, worse on {(do<0).sum()}.\n")
    # (b) reading order multicol vs not
    an["b_reading_order"] = {}
    rows = []
    for r in a.runs:
        mc = mean([data[r][i]["reading_order"] for i in ids if "multicol" in subset[i]["strata"]])
        nm = mean([data[r][i]["reading_order"] for i in ids if "multicol" not in subset[i]["strata"]])
        an["b_reading_order"][r] = {"multicol": mc[0], "n_multicol": mc[1], "non_multicol": nm[0], "n_non_multicol": nm[1]}
        rows.append([LABEL[r], f"{fmt(mc[0])} (N={mc[1]})", f"{fmt(nm[0])} (N={nm[1]})", fmt(mc[0] - nm[0])])
    md.append("**(b) Reading order, multi-column vs. single-column pages (local).**\n")
    md.append(md_table(["Run", "multicol", "non-multicol", "Δ"], rows) + "\n")
    # (c) agreement
    agree = []
    for i in ids:
        tp = norm_text((DEV / P / "predictions" / f"{i}.drbench.md").read_text())
        ts = norm_text((DEV / S / "predictions" / f"{i}.drbench.md").read_text())
        agree.append(difflib.SequenceMatcher(None, tp, ts, autojunk=False).ratio())
    agree = np.array(agree)
    abs_delta = np.abs(delta)
    mean_err = 100 - (po + so) / 2
    rho_d = spearman(agree, abs_delta); rho_e = spearman(agree, mean_err)
    an["c_agreement"] = {"mean_agreement": float(agree.mean()), "median": float(np.median(agree)),
                         "spearman_agree_vs_absdelta": rho_d, "spearman_agree_vs_mean_error": rho_e,
                         "spearman_agree_vs_oracle": spearman(agree, oracle),
                         "n": N}
    # bins
    bins = [(0, .5), (.5, .7), (.7, .85), (.85, 1.01)]
    brow = []
    for lo, hi in bins:
        m = (agree >= lo) & (agree < hi)
        if m.sum():
            brow.append([f"[{lo:.2f},{min(hi,1):.2f})", int(m.sum()), fmt(abs_delta[m].mean()), fmt(mean_err[m].mean()), fmt(oracle[m].mean())])
    an["c_agreement"]["bins"] = brow
    md.append(f"**(c) Inter-tree agreement.** difflib ratio between normalized text of {LABEL[P]} and {LABEL[S]} predictions: "
              f"mean {agree.mean():.3f}, median {np.median(agree):.3f}. Spearman ρ(agreement, |Δ overall|) = {rho_d:.3f}; "
              f"ρ(agreement, mean error of the two) = {rho_e:.3f}; ρ(agreement, oracle overall) = {spearman(agree, oracle):.3f} (N={N}). "
              "Per-page CSV: `runs/dev/agreement_per_page.csv`.\n")
    md.append(md_table(["Agreement bin", "N", "mean |Δ|", "mean error (100−overall)", "mean oracle"], brow) + "\n")
    with open(DEV / "agreement_per_page.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["id", "agreement", "abs_delta", "mean_error", "oracle"])
        for i, g, d, e, o in zip(ids, agree, abs_delta, mean_err, oracle):
            w.writerow([i, f"{g:.4f}", f"{d:.2f}", f"{e:.2f}", f"{o:.2f}"])
    # (d) formulas
    fids = [i for i in ids if data[a.runs[0]][i]["n_gt_formulas"]]
    an["d_formulas"] = {"n_pages_gt_formula": len(fids), "n_gt_formulas": sum(data[a.runs[0]][i]["n_gt_formulas"] for i in fids)}
    rows = []
    for r in a.runs:
        with_f = sum(1 for i in fids if data[r][i]["n_pred_formulas"])
        any_f = sum(1 for i in ids if data[r][i]["n_pred_formulas"])
        dd = sum(1 for i in ids if "$$" in (DEV / r / "predictions" / f"{i}.drbench.md").read_text())
        br = sum(1 for i in ids if "\\[" in (DEV / r / "predictions" / f"{i}.drbench.md").read_text())
        an["d_formulas"][r] = {"pages_with_pred_formula_on_gt_formula_pages": with_f, "pages_with_pred_formula_any": any_f,
                               "pages_using_$$": dd, "pages_using_\\[": br}
        rows.append([LABEL[r], f"{with_f}/{len(fids)}", any_f, dd, br])
    md.append(f"**(d) Formulas.** GT display formulas (`$$…$$`) on {len(fids)} pages ({an['d_formulas']['n_gt_formulas']} formulas). "
              "Note: dev GT Markdown uses `$$…$$`, while the challenge contract asks for `\\[ \\]`.\n")
    md.append(md_table(["Run", "pred has formula on GT-formula pages", "pages with any pred formula", "pages using `$$`", "pages using `\\[`"], rows) + "\n")
    # (e) worst pages
    md.append("**(e) Five worst pages per run (local overall).** Features: len ratio = len(pred)/len(GT); tables/formulas = pred/GT counts.\n")
    an["e_worst"] = {}
    for r in a.runs:
        worst = sorted(ids, key=lambda i: data[r][i]["overall"])[:5]
        rows = []
        an["e_worst"][r] = []
        for i in worst:
            d = data[r][i]
            ratio = d["len_pred"] / max(1, d["len_gt"])
            hyp = []
            if ratio < 0.5: hyp.append("prediction much shorter than GT (missed regions / OCR failure)")
            if ratio > 1.6: hyp.append("prediction much longer than GT (duplicated text / hallucinated regions)")
            if d["n_gt_tables"] and not d["n_pred_tables"]: hyp.append("table(s) in GT not emitted as <table>")
            if d["n_gt_formulas"] and not d["n_pred_formulas"]: hyp.append("display formula(s) missing")
            if "multicol" in subset[i]["strata"]: hyp.append("multi-column layout (reading order)")
            if "fuzzy_scan" in subset[i]["special_issue"]: hyp.append("fuzzy scan")
            if "colorful_backgroud" in subset[i]["special_issue"]: hyp.append("colorful background")
            if not hyp: hyp.append("check manually")
            if i in MANUAL_HYP: hyp.append("manual: " + MANUAL_HYP[i])
            rows.append([i, fmt(d["overall"]), fmt(d["text"]), fmt(d["reading_order"]), fmt(d["teds"]), fmt(d["cdm"]),
                         f"{ratio:.2f}", f"{d['n_pred_tables']}/{d['n_gt_tables']}", f"{d['n_pred_formulas']}/{d['n_gt_formulas']}",
                         "; ".join(hyp)])
            an["e_worst"][r].append({"id": i, "overall": d["overall"], "len_ratio": ratio, "hypothesis": hyp,
                                     "strata": subset[i]["strata"], "special_issue": subset[i]["special_issue"]})
        md.append(f"*{LABEL[r]}*\n")
        md.append(md_table(["id", "overall", "text", "RO", "TEDS", "CDM", "len ratio", "tables", "formulas", "hypothesis"], rows) + "\n")
    out["analyses"] = an

    # ---------- LaTeX ----------
    md.append("## LaTeX (booktabs)\n")
    for name, t in tex:
        md.append(f"### {name}\n```latex\n{t}\n```\n")

    md.append("## Artifacts\n")
    md.append("\n".join(f"- `runs/dev/{r}/reports/local.json`, `local_pages.json`, `local_pages.csv`" for r in a.runs))
    md.append("- `runs/dev/summary.json` (all numbers above), `runs/dev/delta_per_page.csv`, `runs/dev/agreement_per_page.csv`")
    md.append("- `scripts/eval_local.py`, `scripts/eval_summary.py`\n")

    a.out.write_text("\n".join(md))
    (DEV / "summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=float))
    print("\n".join(md[:40]))


if __name__ == "__main__":
    main()
