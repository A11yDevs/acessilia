"""Score a predictions directory and compare two scored runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from docstruct.evaluation.holdout import Verdict, evaluate_candidate
from docstruct.evaluation.markdown import score_markdown_page
from docstruct.evaluation.metrics import PageScores, overall_score

from scripts.bench.datasets import BenchPage

PAGES_FILE = "pages.jsonl"


def score_run(pages: list[BenchPage], predictions: Path, out: Path) -> dict:
    """Write ``report.json``, ``pages.jsonl`` and a worst-first ``drilldown.csv``.

    A page without ground truth is skipped; one without a prediction scores
    against an empty prediction, so a failed page counts as a miss.
    """
    rows: list[tuple[BenchPage, PageScores]] = []
    for page in pages:
        if page.gt_path is None:
            continue
        pred_path = predictions / f"{page.item_id}.md"
        pred = pred_path.read_text(encoding="utf-8") if pred_path.exists() else ""
        gt = page.gt_path.read_text(encoding="utf-8")
        rows.append((page, score_markdown_page(page.item_id, pred, gt)))

    report = overall_score([s for _, s in rows])
    report["pages"] = len(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with open(out / PAGES_FILE, "w", encoding="utf-8") as fh:
        for page, s in rows:
            fh.write(json.dumps({
                "item_id": page.item_id,
                "document_id": page.document_id,
                "page": page.page,
                "overall": s.overall(),
                **_components(s),
            }) + "\n")
    with open(out / "drilldown.csv", "w", newline="", encoding="utf-8") as fh:
        fields = ["item_id", "overall", "text", "teds", "cdm", "reading_order"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        scored = [(p, s) for p, s in rows if s.overall() is not None]
        for page, s in sorted(scored, key=lambda r: r[1].overall()):
            writer.writerow({"item_id": page.item_id, "overall": round(s.overall(), 2),
                             **{k: round(v, 2) for k, v in _components(s).items()}})
    return report


def _components(s: PageScores) -> dict[str, float]:
    """Components on 0–100, higher better (``text`` is 100 × (1 − text_ed))."""
    return {("text" if k == "text_ed" else k): v for k, v in s.components_0_100().items()}


def compare_runs(base: Path, candidate: Path) -> Verdict:
    """Tune/holdout acceptance (``docstruct.evaluation.holdout``) of two scored runs.

    Pages are keyed ``<document_id>_page_<N>`` so the split stays per document.
    """
    return evaluate_candidate(_windows(base), _windows(candidate))


def _windows(run: Path) -> dict[str, dict]:
    windows = {}
    for line in (run / PAGES_FILE).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        windows[f"{row['document_id']}_page_{row['page']}"] = {
            "text": row.get("text"),
            "reading_order": row.get("reading_order"),
            "teds": row.get("teds"),
        }
    return windows
