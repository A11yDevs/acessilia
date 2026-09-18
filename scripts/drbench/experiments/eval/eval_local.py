#!/usr/bin/env python
"""Local (approximate) Dr.DocBench metrics for one run on the dev subset.

Reuses acessilia ``scripts.metrics`` (text_ed, reading_order, teds, cdm) but
with (i) GT located via ``runs/dev/subset.json`` (ids are ``<uuid>_p<N>``,
GT files are ``<uuid>_<N>.md``), (ii) a numpy Levenshtein (identical result,
~50x faster) and (iii) TEDS/CDM conditioned on the GT: pages whose GT has a
table/formula are scorable; a prediction with no table/formula scores 0
(EvalAI behaviour), instead of being silently skipped.

Usage (cwd = repos/acessilia, its .venv):
  python WS/scripts/eval_local.py --run docling --subset WS/runs/dev/subset.json \
      --predictions WS/runs/dev/docling/predictions --out WS/runs/dev/docling/reports
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

WS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WS / "repos" / "acessilia"))

import importlib  # noqa: E402

_ted = importlib.import_module("scripts.metrics.text_ed")
from scripts.metrics.cdm import cdm_score  # noqa: E402
from scripts.metrics.teds import teds_score  # noqa: E402

TABLE_RE = re.compile(r"<table.*?</table>", re.DOTALL | re.IGNORECASE)
GT_FORMULA_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
PRED_FORMULA_RE = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.DOTALL)


def lev_np(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    A = np.frombuffer(a.encode("utf-32-le"), dtype=np.uint32)
    B = np.frombuffer(b.encode("utf-32-le"), dtype=np.uint32)
    m = len(B)
    idx = np.arange(m + 1, dtype=np.int64)
    prev = idx.copy()
    for i, ca in enumerate(A, start=1):
        tmp = np.minimum(prev[:-1] + (B != ca), prev[1:] + 1)
        # cur[j] = min(tmp[j], cur[j-1]+1)  <=>  prefix-min on (value - j)
        d = np.minimum.accumulate(np.concatenate(([i], tmp - idx[1:])))
        prev = d + idx
    return int(prev[-1])


def _selfcheck() -> None:
    import random
    rnd = random.Random(0)
    for _ in range(50):
        a = "".join(rnd.choice("abc \n") for _ in range(rnd.randint(0, 30)))
        b = "".join(rnd.choice("abc \n") for _ in range(rnd.randint(0, 30)))
        assert lev_np(a, b) == _ted.levenshtein(a, b), (a, b)


def norm_lev(a: str, b: str) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    return lev_np(a, b) / max(len(a), len(b))


def _blocks(md: str) -> list[str]:
    return [b.strip() for b in md.split("\n\n") if b.strip()]


def _pair_mean(preds, gts, metric) -> float | None:
    """GT-conditioned pairing: None if GT has none; 0 if pred has none."""
    if not gts:
        return None
    if not preds:
        return 0.0
    vals = [metric(p, g) for p, g in zip(preds, gts)]
    vals = [v if v is not None else 0.0 for v in vals]
    # unmatched GT elements count as 0 (missed)
    vals += [0.0] * max(0, len(gts) - len(preds))
    return sum(vals) / len(vals)


def score_item(args):
    item, pred_dir = args
    pred_path = Path(pred_dir) / f"{item['id']}.drbench.md"
    gt_md = Path(item["md_path"]).read_text(encoding="utf-8")
    if not pred_path.exists():
        return {"id": item["id"], "missing_pred": True}
    pred_md = pred_path.read_text(encoding="utf-8")

    ted = norm_lev(pred_md.strip(), gt_md.strip())
    pb, gb = _blocks(pred_md), _blocks(gt_md)
    if not pb and not gb:
        ro = None
    elif not pb or not gb:
        ro = 0.0
    else:
        ro = (1.0 - norm_lev("\n".join(pb), "\n".join(gb))) * 100.0

    gt_tables = TABLE_RE.findall(gt_md)
    pred_tables = TABLE_RE.findall(pred_md)
    teds = _pair_mean(pred_tables, gt_tables, teds_score)

    gt_f = [m.group(1).strip() for m in GT_FORMULA_RE.finditer(gt_md)]
    pred_f = [(m.group(1) or m.group(2) or "").strip()
              for m in PRED_FORMULA_RE.finditer(pred_md)]
    cdm = _pair_mean(pred_f, gt_f, cdm_score)

    comps = {"text": (1.0 - ted) * 100.0}
    if ro is not None:
        comps["reading_order"] = ro
    if teds is not None:
        comps["teds"] = teds
    if cdm is not None:
        comps["cdm"] = cdm
    return {
        "id": item["id"],
        "strata": item["strata"],
        "layout": item["layout"],
        "special_issue": item["special_issue"],
        "text_ed": ted,
        "text": comps["text"],
        "reading_order": ro,
        "teds": teds,
        "cdm": cdm,
        "overall": sum(comps.values()) / len(comps),
        "n_gt_tables": len(gt_tables),
        "n_pred_tables": len(pred_tables),
        "n_gt_formulas": len(gt_f),
        "n_pred_formulas": len(pred_f),
        "len_pred": len(pred_md),
        "len_gt": len(gt_md),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--subset", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    _selfcheck()

    subset = json.loads(a.subset.read_text())
    with Pool(a.workers) as pool:
        rows = pool.map(score_item, [(it, str(a.predictions)) for it in subset])
    missing = [r["id"] for r in rows if r.get("missing_pred")]
    rows = [r for r in rows if not r.get("missing_pred")]

    def mean(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return (sum(v) / len(v) if v else None), len(v)

    agg = {"run": a.run, "metric_kind": "local (approximate, acessilia scripts.metrics)",
           "n_pages": len(rows), "n_missing_pred": len(missing), "missing": missing}
    for k in ("overall", "text", "text_ed", "reading_order", "teds", "cdm"):
        m, n = mean(k)
        agg[k] = m
        agg[f"n_{k}"] = n
    agg["n_pages_with_gt_table"] = sum(1 for r in rows if r["n_gt_tables"])
    agg["n_pages_with_gt_formula"] = sum(1 for r in rows if r["n_gt_formulas"])
    agg["n_pages_pred_has_table"] = sum(1 for r in rows if r["n_pred_tables"])
    agg["n_pages_pred_has_formula"] = sum(1 for r in rows if r["n_pred_formulas"])

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "local_pages.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    (a.out / "local.json").write_text(json.dumps(agg, indent=2, ensure_ascii=False))
    with open(a.out / "local_pages.csv", "w", newline="") as fh:
        keys = [k for k in rows[0].keys() if k not in ("strata", "special_issue")]
        w = csv.DictWriter(fh, fieldnames=keys + ["strata", "special_issue"])
        w.writeheader()
        for r in rows:
            rr = dict(r)
            rr["strata"] = "|".join(r["strata"])
            rr["special_issue"] = "|".join(r["special_issue"])
            w.writerow(rr)
    print(json.dumps(agg, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
