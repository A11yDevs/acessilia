#!/usr/bin/env python
"""Window-level summary of one official-evaluator run (any split / window size).

Reads <result_dir>/<save_name>_{text_block,reading_order,display_formula}_per_page_edit.json,
_table_per_table_TEDS.json and _display_formula_per_sample_CDM.json and writes a JSON with:
  - per-window components (text, reading_order, teds, formula_1_minus_edit, cdm) x100
  - overall_no_cdm / overall  = mean over windows of the available components (our dev convention)
  - evalai_style = mean of the component means (text, teds, reading_order[, cdm]) — matches the
    EvalAI leaderboard "Overall" within ~0.1.
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("save_name")
ap.add_argument("--result-dir", type=Path, required=True)
ap.add_argument("--out", type=Path, required=True)
a = ap.parse_args()


def load(suffix):
    p = a.result_dir / f"{a.save_name}{suffix}"
    return json.loads(p.read_text()) if p.exists() else {}


def mean(vals):
    vals = [v for v in vals if v is not None]
    return (float(np.mean(vals)) if vals else None), len(vals)


text = load("_text_block_per_page_edit.json")
ro = load("_reading_order_per_page_edit.json")
form = load("_display_formula_per_page_edit.json")
teds_w, cdm_w = defaultdict(list), defaultdict(list)
for k, v in load("_table_per_table_TEDS.json").items():
    teds_w[re.sub(r"_\[\d+\]$", "", k)].append(v["TEDS"])
for k, v in load("_display_formula_per_sample_CDM.json").items():
    cdm_w[re.sub(r"_\[?\d+\]?$", "", k)].append(float(v))

keys = set(text) | set(ro) | set(form) | set(teds_w)
rows = []
for k in sorted(keys):
    comps = {}
    if k in text:
        comps["text"] = (1 - text[k]) * 100
    if k in ro:
        comps["reading_order"] = (1 - ro[k]) * 100
    if k in teds_w:
        comps["teds"] = float(np.mean(teds_w[k])) * 100
    no_cdm = (sum(comps.values()) / len(comps)) if comps else None
    cdm = float(np.mean(cdm_w[k])) * 100 if k in cdm_w else None
    if cdm is not None:
        comps["cdm"] = cdm
    rows.append({"window": k, "text": comps.get("text"), "reading_order": comps.get("reading_order"),
                 "teds": comps.get("teds"), "formula_1_minus_edit": (1 - form[k]) * 100 if k in form else None,
                 "cdm": cdm, "overall_no_cdm": no_cdm,
                 "overall": (sum(comps.values()) / len(comps)) if comps else None})

agg = {"save_name": a.save_name, "n_windows": len(rows)}
for c in ("overall", "overall_no_cdm", "text", "reading_order", "teds", "formula_1_minus_edit", "cdm"):
    agg[c], agg[f"n_{c}"] = mean([r[c] for r in rows])
comp_means = [agg[c] for c in ("text", "teds", "reading_order") if agg[c] is not None]
agg["evalai_style_no_cdm"] = float(np.mean(comp_means)) if comp_means else None
agg["evalai_style"] = float(np.mean(comp_means + ([agg["cdm"]] if agg["cdm"] is not None else []))) if comp_means else None
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps({"summary": agg, "windows": rows}, indent=1))
f = lambda v: "–" if v is None else f"{v:.1f}"
print(f"{a.save_name}: windows={agg['n_windows']} overall_no_cdm={f(agg['overall_no_cdm'])} "
      f"evalai_style={f(agg['evalai_style_no_cdm'])} text={f(agg['text'])} RO={f(agg['reading_order'])} "
      f"TEDS={f(agg['teds'])} (n={agg['n_teds']}) formula={f(agg['formula_1_minus_edit'])} (n={agg['n_formula_1_minus_edit']}) "
      f"CDM={f(agg['cdm'])} (n={agg['n_cdm']})")
