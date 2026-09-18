#!/usr/bin/env python
"""Append an "Adjudicator v0" section to runs/dev/summary.md (+ summary.json).

Reads runs/dev/<run>/reports/{local.json,official.json} for the 5 runs,
runs/dev/adjudicator-v0*/predictions/decisions.csv, and the oracle numbers
already stored in runs/dev/summary.json (table4 / official.table4).
Run AFTER scripts/eval_summary.py and scripts/official_summary.py.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

WS = Path(__file__).resolve().parents[1]
DEV = WS / "runs/dev"
RUNS = sys.argv[1:] or ["docling", "docling-forceocr", "mineru", "adjudicator-v0", "adjudicator-v0b"]
LABEL = {"docling": "Docling (default)", "docling-forceocr": "Docling (force OCR)", "mineru": "MinerU",
         "adjudicator-v0": "Adjudicator v0", "adjudicator-v0b": "Adjudicator v0b (agreement)"}
SHORT = {"docling": "Docling", "docling-forceocr": "Docling-fOCR", "mineru": "MinerU",
         "adjudicator-v0": "Adj. v0", "adjudicator-v0b": "Adj. v0b"}


def fmt(v):
    return "–" if v is None else f"{v:.1f}"


def load(run, name):
    p = DEV / run / "reports" / name
    return json.loads(p.read_text()) if p.exists() else None


def md_table(header, rows):
    out = ["| " + " | ".join(map(str, header)) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join(out + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def tex_table(header, rows, caption, label):
    L = [r"\begin{table}[t]", r"\centering", r"\small", r"\begin{tabular}{l" + "r" * (len(header) - 1) + "}", r"\toprule",
         " & ".join(map(str, header)) + r" \\", r"\midrule"] + [" & ".join(map(str, r)) + r" \\" for r in rows] + \
        [r"\bottomrule", r"\end{tabular}", rf"\caption{{{caption}}}", rf"\label{{{label}}}", r"\end{table}"]
    return "\n".join(L)


local = {r: load(r, "local.json") for r in RUNS}
official = {r: load(r, "official.json") for r in RUNS}
runs = [r for r in RUNS if local[r] and official[r]]
sj = json.loads((DEV / "summary.json").read_text())
oracle_local = sj.get("table4", {}).get("oracle")
oracle_off = None
for row in sj.get("official", {}).get("table4", []):
    if str(row[0]).startswith("Per-page oracle"):
        oracle_off = float(row[2])

md = ["\n## Adjudicator v0 (per-page router, no new inference)\n",
      "Rule v0 (`scripts/adjudicate_v0.py`): MinerU if its output has `<table` or a formula (`$$`, `\\[`, `\\(`); "
      "else the non-empty output if exactly one has <40 chars of useful text; else Docling (force OCR). "
      "v0b: if difflib agreement between the two normalized texts ≥ 0.85 choose Docling, else apply v0. "
      "Inputs: `runs/dev/docling-forceocr/predictions` + `runs/dev/mineru/predictions`; outputs "
      "`runs/dev/adjudicator-v0{,b}/predictions/{*.drbench.md,decisions.csv}`; reports `runs/dev/adjudicator-v0{,b}/reports/{local,official}.json`.\n"]

# ---- side-by-side table: local + official ----
hdr = ["Metric", "N"] + [SHORT[r] for r in runs]
rows = []
for key, name in (("overall", "Overall (local)"), ("text", "Text (local)"), ("reading_order", "Reading order (local)"),
                  ("teds", "TEDS (local)"), ("cdm", "CDM token-F1 (local)")):
    rows.append([name, local[runs[0]][f"n_{key}"]] + [fmt(local[r][key]) for r in runs])
rows_off = []
for key, name in (("overall_no_cdm", "Overall, no CDM (official)"), ("text", "Text (official)"),
                  ("reading_order", "Reading order (official)"), ("teds", "TEDS (official)"),
                  ("formula_1_minus_edit", "Formula 1−Edit (official, not in overall)")):
    ns = [official[r][f"n_{key}"] for r in runs]
    rows_off.append([name, max(ns)] + [fmt(official[r][key]) for r in runs])
md.append("### Table 5 — Adjudicator vs. single systems (dev subset)\n")
md.append(md_table(hdr, rows + rows_off) + "\n")
md.append(f"Per-page oracle (Docling force OCR vs MinerU): local {fmt(oracle_local)}, official (no CDM) {fmt(oracle_off)}. "
          "Local/official scores are *not* comparable with each other (see methodology above).\n")

# ---- oracle comparison ----
orc = [["Best single system (MinerU)", fmt(local["mineru"]["overall"]), fmt(official["mineru"]["overall_no_cdm"])]]
for r in ("adjudicator-v0", "adjudicator-v0b"):
    if r in runs:
        orc.append([LABEL[r], fmt(local[r]["overall"]), fmt(official[r]["overall_no_cdm"])])
        orc.append([f"  Δ vs. MinerU", f"{local[r]['overall'] - local['mineru']['overall']:+.1f}",
                    f"{official[r]['overall_no_cdm'] - official['mineru']['overall_no_cdm']:+.1f}"])
        if oracle_local is not None and oracle_off is not None:
            orc.append([f"  gap to oracle", f"{local[r]['overall'] - oracle_local:+.1f}",
                        f"{official[r]['overall_no_cdm'] - oracle_off:+.1f}"])
orc.append(["Per-page oracle (max)", fmt(oracle_local), fmt(oracle_off)])
md.append("### Table 6 — Adjudicator vs. oracle (overall)\n")
md.append(md_table(["System", "Local", "Official (no CDM)"], orc) + "\n")

# ---- decisions ----
dec = {}
for r in ("adjudicator-v0", "adjudicator-v0b"):
    p = DEV / r / "predictions" / "decisions.csv"
    if not p.exists():
        continue
    rows_d = list(csv.DictReader(p.open()))
    dec[r] = {"n": len(rows_d), "choice": dict(Counter(x["choice"] for x in rows_d)),
              "reason": dict(Counter(x["reason"] for x in rows_d))}
    md.append(f"**Decisions {LABEL[r]}** (N={len(rows_d)}): choice " +
              ", ".join(f"{k}={v}" for k, v in sorted(dec[r]["choice"].items())) + ".\n")
    md.append(md_table(["Reason", "N", "choice"],
                       [[k, v, next(x["choice"] for x in rows_d if x["reason"] == k)]
                        for k, v in sorted(dec[r]["reason"].items(), key=lambda kv: -kv[1])]) + "\n")

md.append("### LaTeX (adjudicator)\n```latex\n" + tex_table(hdr, rows + rows_off,
          "Adjudicator v0 (per-page router) vs. single systems on the dev subset. Local = approximate metrics; "
          "official = DrDocBench evaluator, 1-page windows, CDM not computed. N = scorable pages.", "tab:adjudicator") + "\n```\n")
md.append("```latex\n" + tex_table(["System", "Local", "Official (no CDM)"], orc,
          "Adjudicator v0 overall score against the best single system and the per-page oracle.", "tab:adjudicator-oracle") + "\n```\n")

summary = DEV / "summary.md"
txt = summary.read_text()
marker = "\n## Adjudicator v0"
if marker in txt:
    txt = txt[:txt.index(marker)]
summary.write_text(txt + "\n".join(md))
sj["adjudicator"] = {"runs": runs, "table5_local": rows, "table5_official": rows_off, "table6": orc,
                     "decisions": dec, "oracle_local": oracle_local, "oracle_official": oracle_off}
(DEV / "summary.json").write_text(json.dumps(sj, indent=1, ensure_ascii=False, default=float))
print("\n".join(md))
