#!/usr/bin/env python
"""Benchmark runner: score predictions against Dr.DocBench ground truth.

Phase 1 improvements:
- All tables and formulas on a page are paired (N:N by order of appearance),
  not just the first one.
- Ground truth is fetched from the Toolbox dataset by default; a local
  ``--gt-dir`` fallback is still supported.
- Per-page drill-down CSV with the worst pages per component.

Usage:
    python -m scripts.drbench.eval_run --predictions var/drbench/predictions \
        --provider docling-mvp --report var/drbench/reports/baseline.json
    # local GT fallback:
    python -m scripts.drbench.eval_run --predictions var/drbench/predictions \
        --gt-dir var/drbench/dev --provider docling-mvp
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

TABLE_RE = re.compile(r"<table.*?</table>", re.DOTALL | re.IGNORECASE)
DISPLAY_FORMULA_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Eval Dr.DocBench predictions")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--gt-dir", type=Path, default=None,
                        help="optional local dir with ground-truth .md files "
                             "(default: fetch GT from the Toolbox dataset)")
    parser.add_argument("--split", default="dev",
                        help="Toolbox split to fetch GT from (default: dev)")
    parser.add_argument("--provider", default="docling",
                        help="label for the CSV tracking column")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    from scripts.metrics.cdm import cdm_score
    from scripts.metrics.overall import PageScores, overall_score
    from scripts.metrics.reading_order import reading_order_score
    from scripts.metrics.teds import teds_score
    from scripts.metrics.text_ed import text_ed

    gt_loader = _make_gt_loader(args.gt_dir, args.split)

    pages: list[PageScores] = []
    for md_path in sorted(args.predictions.glob("*.drbench.md")):
        item_id = md_path.name.removesuffix(".drbench.md")
        gt_md = gt_loader(item_id)
        if gt_md is None:
            print(f"[WARN] no GT for {item_id}", file=sys.stderr)
            continue
        pred_md = md_path.read_text(encoding="utf-8")

        s = PageScores(item_id=item_id)
        s.text_ed = text_ed(pred_md, gt_md)
        s.reading_order = reading_order_score(
            [b for b in pred_md.split("\n\n") if b.strip()],
            [b for b in gt_md.split("\n\n") if b.strip()],
        )
        s.teds = _pairwise_mean(
            _extract_tables(pred_md), _extract_tables(gt_md), teds_score
        )
        s.cdm = _pairwise_mean(
            _extract_formulas(pred_md), _extract_formulas(gt_md), cdm_score
        )
        pages.append(s)

    report = overall_score(pages)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        csv_path = args.report.parent / "tracking.csv"
        write_csv(csv_path, args.provider, pages, report)
        drill_path = args.report.parent / f"drilldown-{args.provider}.csv"
        write_drilldown(drill_path, pages)
        print(f"Report saved to {args.report}; tracking at {csv_path}; "
              f"drill-down at {drill_path}")
    return 0


def _make_gt_loader(gt_dir: Path | None, split: str):
    """Return a callable item_id -> gt markdown (or None).

    Prefers the Toolbox dataset when no local --gt-dir is given.
    """
    if gt_dir is not None:
        def local_loader(item_id: str) -> str | None:
            matches = list(gt_dir.rglob(f"*{item_id}*.md"))
            if not matches:
                return None
            return matches[0].read_text(encoding="utf-8")
        return local_loader

    from backend.tools.toolbox_dataset_tools import (
        toolbox_get_drbench_ground_truth,
        toolbox_get_drbench_item,
    )

    md_path_cache: dict[str, str] = {}

    def toolbox_loader(item_id: str) -> str | None:
        md_path = md_path_cache.get(item_id)
        if md_path is None:
            item = toolbox_get_drbench_item(item_id, split=split)
            if item is None:
                return None
            for ref in item.get("artifacts", []):
                path = str(ref.get("path", ""))
                if path.endswith(".md"):
                    md_path = path
                    break
            if md_path is None:
                return None
            md_path_cache[item_id] = md_path
        data = toolbox_get_drbench_ground_truth(item_id, md_path, split=split)
        return data.decode("utf-8") if data else None

    return toolbox_loader


def _extract_tables(md: str) -> list[str]:
    return [m.group(0) for m in TABLE_RE.finditer(md)]


def _extract_formulas(md: str) -> list[str]:
    return [m.group(1).strip() for m in DISPLAY_FORMULA_RE.finditer(md)]


def _pairwise_mean(preds: list[str], gts: list[str], metric) -> float | None:
    """Pair predicted elements with GT elements by order of appearance.

    Scores each pair and returns the mean. Pages where either side has no
    elements of this type are non-scorable for the component (None), matching
    the EvalAI missing-component behavior. When counts diverge, extra
    elements on either side are ignored (order-based pairing).
    """
    if not preds or not gts:
        return None
    scores = [metric(p, g) for p, g in zip(preds, gts)]
    valid = [v for v in scores if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def write_csv(csv_path: Path, provider: str, pages, report: dict) -> None:
    """Append/refresh per-provider tracking rows."""
    is_new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["provider", "pages", "text_0_100", "teds", "cdm",
                             "reading_order", "overall"])
        writer.writerow([
            provider,
            len([p for p in pages if p.components_0_100()]),
            # text_ed is 0–1 (lower better); convert to 0–100 (higher better)
            # for consistency with the other components and the report.
            round((1.0 - report.get("text_ed", 1.0)) * 100.0, 2),
            round(report.get("teds", 0.0), 2),
            round(report.get("cdm", 0.0), 2),
            round(report.get("reading_order", 0.0), 2),
            round(report.get("overall", 0.0), 2),
        ])


def write_drilldown(csv_path: Path, pages) -> None:
    """Per-page × component CSV, sorted by overall ascending (worst first)."""
    rows = []
    for p in pages:
        comps = p.components_0_100()
        if not comps:
            continue
        rows.append({
            "item_id": p.item_id,
            "overall": round(p.overall(), 2),
            "text_0_100": round(comps["text_ed"], 2)
            if "text_ed" in comps else "",
            "teds": round(comps["teds"], 2) if "teds" in comps else "",
            "cdm": round(comps["cdm"], 2) if "cdm" in comps else "",
            "reading_order": round(comps["reading_order"], 2)
            if "reading_order" in comps else "",
        })
    rows.sort(key=lambda r: r["overall"])
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "item_id", "overall", "text_0_100", "teds", "cdm", "reading_order",
        ])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
