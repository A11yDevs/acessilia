"""CLI for acessilia-metrics: score a predictions.jsonl against ground truth.

Usage:
    acessilia-metrics score predictions.jsonl --gt-dir mds/ --report report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .overall import PageScores, overall_score


def score_submission(predictions_path: Path, gt_dir: Path) -> dict:
    """Score a predictions.jsonl against a ground-truth markdown tree."""
    from scripts.metrics.cdm import cdm_score
    from scripts.metrics.reading_order import reading_order_score
    from scripts.metrics.teds import teds_score
    from scripts.metrics.text_ed import text_ed

    pages: list[PageScores] = []
    with open(predictions_path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            pred = json.loads(line)
            item_id = pred.get("item_id") or f"{pred['document_id']}_p{pred['page']}"
            gt_path = _find_gt(gt_dir, pred, item_id)
            if gt_path is None:
                continue
            gt_md = gt_path.read_text(encoding="utf-8")
            pred_md = pred.get("markdown", "")

            scores = PageScores(item_id=item_id)
            # Text component: full-page normalized edit distance.
            scores.text_ed = text_ed(pred_md, gt_md)
            # Reading order: paragraph block sequences.
            scores.reading_order = reading_order_score(
                _blocks(pred_md), _blocks(gt_md)
            )
            # Table TEDS: compare first tables found on each side.
            pred_table = _first_table(pred_md)
            gt_table = _first_table(gt_md)
            if pred_table and gt_table:
                scores.teds = teds_score(pred_table, gt_table)
            # CDM: compare first display formulas found on each side.
            pred_f = _first_formula(pred_md)
            gt_f = _first_formula(gt_md)
            if pred_f and gt_f:
                scores.cdm = cdm_score(pred_f, gt_f)
            pages.append(scores)

    return overall_score(pages)


def _find_gt(gt_dir: Path, pred: dict, item_id: str) -> Path | None:
    candidates = [
        gt_dir / f"{item_id}.md",
        gt_dir / pred.get("document_id", "") / f"page_{pred.get('page')}.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    matches = list(gt_dir.rglob(f"*{item_id}*.md"))
    return matches[0] if matches else None


def _blocks(md: str) -> list[str]:
    return [b.strip() for b in md.split("\n\n") if b.strip()]


def _first_table(md: str) -> str | None:
    import re

    m = re.search(r"<table.*?</table>", md, re.DOTALL | re.IGNORECASE)
    return m.group(0) if m else None


def _first_formula(md: str) -> str | None:
    import re

    m = re.search(r"\$\$(.+?)\$\$", md, re.DOTALL)
    return m.group(1) if m else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acessilia-metrics")
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="score predictions vs ground truth")
    p_score.add_argument("predictions", type=Path)
    p_score.add_argument("--gt-dir", type=Path, required=True)
    p_score.add_argument("--report", type=Path, default=None)

    args = parser.parse_args(argv)
    report = score_submission(args.predictions, args.gt_dir)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
