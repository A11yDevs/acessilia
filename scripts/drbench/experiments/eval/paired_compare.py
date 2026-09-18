#!/usr/bin/env python
"""Paired per-page comparison of two dev runs under the OFFICIAL evaluator.

Reads runs/dev/<run>/reports/official_pages.json (written by official_summary.py),
pairs pages by id, and for every component reports mean delta, wins/losses/ties,
an exact two-sided sign test and a 95% bootstrap CI of the mean delta.

Usage: paired_compare.py <runA> <runB> [--tie 0.5] [--json out.json]
Delta = B - A (positive means B is better).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

WS = Path(__file__).resolve().parents[1]
DEV = WS / "runs/dev"
COMPONENTS = ["overall_no_cdm", "text", "reading_order", "teds", "formula_1_minus_edit", "cdm"]


def load(run: str) -> dict[str, dict]:
    p = DEV / run / "reports" / "official_pages.json"
    if not p.exists():
        raise SystemExit(f"missing {p} (run official_summary.py first)")
    return {r["id"]: r for r in json.loads(p.read_text())}


def sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_ci(d: np.ndarray, iters: int = 10000, seed: int = 13) -> tuple[float, float]:
    if len(d) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(iters, len(d)))
    means = d[idx].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def compare(a: str, b: str, tie: float) -> dict:
    A, B = load(a), load(b)
    ids = sorted(set(A) & set(B))
    out = {"run_a": a, "run_b": b, "n_pages_common": len(ids), "n_only_a": len(set(A) - set(B)),
           "n_only_b": len(set(B) - set(A)), "tie_threshold": tie, "components": {}}
    for c in COMPONENTS:
        pairs = [(A[i].get(c), B[i].get(c)) for i in ids]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if not pairs:
            continue
        x = np.array([p[0] for p in pairs]); y = np.array([p[1] for p in pairs]); d = y - x
        wins, losses = int((d > tie).sum()), int((d < -tie).sum())
        lo, hi = bootstrap_ci(d)
        out["components"][c] = {"n": len(d), "mean_a": float(x.mean()), "mean_b": float(y.mean()),
                                "delta": float(d.mean()), "ci95": [lo, hi], "wins_b": wins, "losses_b": losses,
                                "ties": len(d) - wins - losses, "sign_test_p": sign_test(wins, losses),
                                "median_delta": float(np.median(d))}
    return out


def to_markdown(r: dict) -> str:
    L = [f"### {r['run_b']} vs {r['run_a']} (Δ = B − A, N={r['n_pages_common']} common pages, tie |Δ|≤{r['tie_threshold']})",
         "", "| component | N | A | B | Δ | 95% CI | B wins/losses/ties | sign p |", "|---|---|---|---|---|---|---|---|"]
    for c, v in r["components"].items():
        L.append(f"| {c} | {v['n']} | {v['mean_a']:.1f} | {v['mean_b']:.1f} | {v['delta']:+.2f} | "
                 f"[{v['ci95'][0]:+.2f}, {v['ci95'][1]:+.2f}] | {v['wins_b']}/{v['losses_b']}/{v['ties']} | {v['sign_test_p']:.3f} |")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_a"); ap.add_argument("run_b")
    ap.add_argument("--tie", type=float, default=0.5)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    res = compare(args.run_a, args.run_b, args.tie)
    print(to_markdown(res))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(res, indent=1))
