#!/usr/bin/env python
"""Append one line per evaluated run to runs/dev/LEDGER.md and apply the PLAN.md §8.2.5
acceptance rule against a baseline run (default adjudicator-v0).

Usage: ledger_append.py <run_id> [--baseline adjudicator-v0] [--note "..."]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WS = Path(__file__).resolve().parents[1]
DEV = WS / "runs/dev"
LEDGER = DEV / "LEDGER.md"
HEADER = ("| date (UTC) | run | N | overall | no-CDM | text | RO | TEDS | formula | CDM | baseline | Δ no-CDM | decision | note |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
TOL, MAX_DROP = 0.3, 1.0


def rep(run: str) -> dict:
    p = DEV / run / "reports" / "official.json"
    return json.loads(p.read_text()) if p.exists() else {}


def f(v, nd=1):
    return "–" if v is None else f"{v:.{nd}f}"


def git_short(repo: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(WS / "repos" / repo), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "?"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id"); ap.add_argument("--baseline", default="adjudicator-v0"); ap.add_argument("--note", default="")
    a = ap.parse_args()
    r, b = rep(a.run_id), rep(a.baseline)
    if not r:
        raise SystemExit(f"no official.json for {a.run_id}")
    delta = None if not b or r.get("overall_no_cdm") is None else r["overall_no_cdm"] - b["overall_no_cdm"]
    decision = "n/a"
    if delta is not None:
        drops = [c for c in ("text", "reading_order", "teds") if r.get(c) is not None and b.get(c) is not None and b[c] - r[c] > MAX_DROP]
        decision = "ACCEPT" if delta >= -TOL and not drops else ("REJECT: " + (", ".join(f"{c}↓" for c in drops) if drops else f"Δ<{-TOL}"))
    note = (a.note + " " if a.note else "") + f"acessilia@{git_short('acessilia')} toolbox@{git_short('acessilia-toolbox')}"
    line = (f"| {datetime.now(timezone.utc):%Y-%m-%d %H:%M} | {a.run_id} | {r.get('n_pages_in_pred_tree')} | {f(r.get('overall'))} | {f(r.get('overall_no_cdm'))} | "
            f"{f(r.get('text'))} | {f(r.get('reading_order'))} | {f(r.get('teds'))} | {f(r.get('formula_1_minus_edit'))} | {f(r.get('cdm'))} | "
            f"{a.baseline} | {'–' if delta is None else f'{delta:+.2f}'} | {decision} | {note} |\n")
    if not LEDGER.exists():
        LEDGER.write_text("# Dev-120 ledger (official evaluator; see PLAN.md §8.2)\n\n" + HEADER)
    LEDGER.open("a").write(line)
    print(line, end="")
