#!/usr/bin/env python
"""Per-page aggregation of the OFFICIAL DrDocBench evaluator outputs
(runs/dev/official/result/<run>_*_per_page_edit.json, <run>_table_per_table_TEDS.json)
into runs/dev/<run>/reports/official_pages.json + official.json, plus a
Markdown section appended to runs/dev/summary.md.

Overall(official, no CDM) = per-page mean of available components among
text (1-Edit)x100, reading order (1-Edit)x100, TEDS x100. CDM is not computed
(needs TeX Live); formula (1-Edit)x100 is reported separately and NOT folded
into the overall.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

WS = Path(__file__).resolve().parents[1]
DEV = WS / "runs/dev"
RES = DEV / "official/result"
RUNS = sys.argv[1:] or ["docling", "docling-forceocr", "mineru"]
class _Label(dict):
    def __missing__(self, k):
        return k


LABEL = _Label({"docling": "Docling (default)", "docling-forceocr": "Docling (force OCR)", "mineru": "MinerU",
                "adjudicator-v0": "Adjudicator v0", "adjudicator-v0b": "Adjudicator v0b (agreement)"})
STRATA = ["plain", "multicol", "special", "table", "equation"]
subset = {it["id"]: it for it in json.loads((DEV / "subset.json").read_text())}
key2id = {f"{it['document_id']}_page_{it['page']}-{it['page']}.jpg": i for i, it in subset.items()}


def load(name):
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else {}


def fmt(v, nd=1):
    return "–" if v is None else f"{v:.{nd}f}"


def mean(vals):
    vals = [v for v in vals if v is not None]
    return (float(np.mean(vals)) if vals else None), len(vals)


per_run = {}
for r in RUNS:
    text = load(f"{r}_text_block_per_page_edit.json")
    ro = load(f"{r}_reading_order_per_page_edit.json")
    form = load(f"{r}_display_formula_per_page_edit.json")
    teds_tab = load(f"{r}_table_per_table_TEDS.json")
    teds_pages = defaultdict(list)
    for k, v in teds_tab.items():
        teds_pages[re.sub(r"_\[\d+\]$", "", k)].append(v["TEDS"])
    # per-formula CDM (only present when the run was scored with end2end_full.yaml)
    cdm_pages = defaultdict(list)
    for k, v in load(f"{r}_display_formula_per_sample_CDM.json").items():
        cdm_pages[re.sub(r"_\[?\d+\]?$", "", k)].append(float(v))
    has_cdm = bool(cdm_pages)
    rows = {}
    for key, i in key2id.items():
        comps = {}
        if key in text:
            comps["text"] = (1 - text[key]) * 100
        if key in ro:
            comps["reading_order"] = (1 - ro[key]) * 100
        if key in teds_pages:
            comps["teds"] = float(np.mean(teds_pages[key])) * 100
        formula = (1 - form[key]) * 100 if key in form else None
        cdm = float(np.mean(cdm_pages[key])) * 100 if key in cdm_pages else None
        overall_no_cdm = (sum(comps.values()) / len(comps)) if comps else None
        if cdm is not None:
            comps["cdm"] = cdm
        rows[i] = {"id": i, **{c: comps.get(c) for c in ("text", "reading_order", "teds")},
                   "formula_1_minus_edit": formula, "cdm": cdm,
                   "overall_no_cdm": overall_no_cdm,
                   "overall": (sum(comps.values()) / len(comps)) if (comps and has_cdm) else None,
                   "n_components": len(comps)}
    per_run[r] = rows
    agg = {"run": r, "metric_kind": "official DrDocBench evaluator (multipage_pdf_validation.py, 1-page window, quick_match)"
           + (", CDM computed locally" if has_cdm else ", CDM not computed"),
           "n_pages_in_pred_tree": len(rows)}
    for k in ("overall", "overall_no_cdm", "text", "reading_order", "teds", "formula_1_minus_edit", "cdm"):
        m, n = mean([v[k] for v in rows.values()])
        agg[k], agg[f"n_{k}"] = m, n
    mr = load(f"{r}_metric_result.json")
    agg["metric_result_summary"] = {
        "text_block_edit_page_avg": mr.get("text_block", {}).get("all", {}).get("Edit_dist", {}).get("ALL_page_avg"),
        "reading_order_edit_page_avg": mr.get("reading_order", {}).get("all", {}).get("Edit_dist", {}).get("ALL_page_avg"),
        "table_TEDS_all": mr.get("table", {}).get("all", {}).get("TEDS", {}).get("all"),
        "table_TEDS_structure_only": mr.get("table", {}).get("all", {}).get("TEDS_structure_only", {}).get("all"),
        "display_formula_edit_page_avg": mr.get("display_formula", {}).get("all", {}).get("Edit_dist", {}).get("ALL_page_avg"),
        "display_formula_CDM_all": mr.get("display_formula", {}).get("all", {}).get("CDM", {}).get("all") if isinstance(mr.get("display_formula", {}).get("all", {}).get("CDM"), dict) else None,
    }
    out = DEV / r / "reports"
    (out / "official_pages.json").write_text(json.dumps(list(rows.values()), indent=1))
    (out / "official.json").write_text(json.dumps(agg, indent=2))

# ---- tables ----
ids = sorted(set.intersection(*(set(v) for v in per_run.values())))
md = ["\n## OFFICIAL evaluator (DrDocBench `multipage_pdf_validation.py`, 1-page windows, quick_match; CDM not computed)\n",
      "Per-page files: `runs/dev/official/result/<run>_*_per_page_edit.json`, `<run>_table_per_table_TEDS.json`; "
      "aggregates: `runs/dev/<run>/reports/official.json`, `official_pages.json`. "
      "Config: `runs/dev/eval-configs/end2end_nocdm.yaml`. Scores are (1−Edit)×100 for text / reading order / formula and TEDS×100; "
      "**Overall (official, no CDM)** = per-page mean of text, reading order and TEDS where the GT has them. "
      "Pages whose GT has no text block (figure-only) are non-scorable for text/RO and thus excluded from those N.\n"]
header = ["Metric (official)", "N"] + [LABEL[r] for r in RUNS]
rows = []
tex_rows = []
for key, name in (("overall_no_cdm", "Overall (no CDM)"), ("overall", "Overall (with local CDM)"), ("text", "Text (1−Edit)×100"), ("reading_order", "Reading order (1−Edit)×100"),
                  ("teds", "TEDS×100"), ("formula_1_minus_edit", "Formula (1−Edit)×100, not in overall"), ("cdm", "CDM×100 (local TeX)")):
    vals = {r: mean([per_run[r][i].get(key) for i in ids]) for r in RUNS}
    if all(v[1] == 0 for v in vals.values()):
        continue
    rows.append([name, max(v[1] for v in vals.values())] + [fmt(vals[r][0]) for r in RUNS])
md.append("### Table 2 (official)\n")
md.append("| " + " | ".join(header) + " |\n|" + "|".join("---" for _ in header) + "|\n" + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in rows) + "\n")
# strata
srows = []
for s in STRATA:
    sid = [i for i in ids if s in subset[i]["strata"]]
    vals = {r: mean([per_run[r][i]["overall_no_cdm"] for i in sid]) for r in RUNS}
    srows.append([s, vals[RUNS[0]][1]] + [fmt(vals[r][0]) for r in RUNS])
md.append("### Table 3 (official overall, no CDM, by stratum)\n")
h3 = ["Stratum", "N scorable"] + [LABEL[r] for r in RUNS]
md.append("| " + " | ".join(h3) + " |\n|" + "|".join("---" for _ in h3) + "|\n" + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in srows) + "\n")
# oracle
P, S = "docling-forceocr", "mineru"
pair = [(per_run[P][i]["overall_no_cdm"], per_run[S][i]["overall_no_cdm"]) for i in ids]
pair = [(x, y) for x, y in pair if x is not None and y is not None]
po = np.array([x for x, _ in pair]); so = np.array([y for _, y in pair]); d = po - so
orc = np.maximum(po, so)
o4 = [["Docling (force OCR)", len(pair), fmt(po.mean())], ["MinerU", len(pair), fmt(so.mean())],
      ["Per-page oracle (max)", len(pair), fmt(orc.mean())], ["Gain vs. best single", len(pair), f"+{orc.mean()-max(po.mean(), so.mean()):.1f}"],
      ["Pages won by Docling / MinerU / tie (|Δ|<0.5)", len(pair), f"{int((d>=0.5).sum())} / {int((d<=-0.5).sum())} / {int((np.abs(d)<0.5).sum())}"]]
md.append("### Table 4 (official overall, no CDM)\n")
md.append("| System | N | Overall (official, no CDM) |\n|---|---|---|\n" + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in o4) + "\n")
md.append(f"Δ official = Docling(force OCR) − MinerU: min {d.min():.1f}, Q1 {np.percentile(d,25):.1f}, median {np.median(d):.1f}, "
          f"Q3 {np.percentile(d,75):.1f}, max {d.max():.1f} (mean {d.mean():.1f}).\n")


def tex(header, rows, caption, label):
    L = [r"\begin{table}[t]", r"\centering", r"\small", r"\begin{tabular}{l" + "r" * (len(header) - 1) + "}", r"\toprule",
         " & ".join(header) + r" \\", r"\midrule"] + [" & ".join(map(str, r)) + r" \\" for r in rows] + \
        [r"\bottomrule", r"\end{tabular}", rf"\caption{{{caption}}}", rf"\label{{{label}}}", r"\end{table}"]
    return "\n".join(L)


md.append("### LaTeX (official)\n```latex\n" + tex(header, rows, "Official DrDocBench evaluator on the dev subset (1-page windows; CDM not computed). N = scorable pages.", "tab:main-official") + "\n```\n")
md.append("```latex\n" + tex(h3, srows, "Official overall (no CDM) by stratum.", "tab:strata-official") + "\n```\n")
md.append("```latex\n" + tex(["System", "N", "Overall (official, no CDM)"], o4, "Per-page oracle under the official evaluator (no CDM).", "tab:oracle-official") + "\n```\n")

summary = DEV / "summary.md"
txt = summary.read_text()
marker = "\n## OFFICIAL evaluator"
if marker in txt:
    txt = txt[:txt.index(marker)]
summary.write_text(txt + "\n".join(md))
sj = DEV / "summary.json"
sjd = json.loads(sj.read_text()) if sj.exists() else {}
sjd["official"] = {"table2": rows, "table3": srows, "table4": o4, "n_pairs": len(pair),
                   "delta_stats": {"min": float(d.min()), "q1": float(np.percentile(d, 25)), "median": float(np.median(d)),
                                   "q3": float(np.percentile(d, 75)), "max": float(d.max()), "mean": float(d.mean())}}
sj.write_text(json.dumps(sjd, indent=1, ensure_ascii=False, default=float))
print("\n".join(md))
