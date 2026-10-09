"""Compare official per-page scores without hiding missing metrics or regressions."""
from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

from scripts.drbench.experiments.eval.frozen_inputs import write_json

METRICS = ("reading_order", "text_block", "table", "display_formula", "table_teds")
TOLERANCE = 1e-9  # Floating-point equality, not an allowed quality loss.


def check_inventory(directory: Path, pages: list[dict]) -> None:
    expected = {p["id"] for p in pages}
    actual = {p.name.removesuffix(".drbench.md") for p in directory.glob("*.drbench.md")}
    if actual != expected:
        raise ValueError(f"Prediction coverage mismatch: missing={sorted(expected-actual)}, "
                         f"extra={sorted(actual-expected)}")


def metric_score(result: Path, prefix: str, metric: str, page: dict) -> tuple[float | None, str]:
    component = "table" if metric == "table_teds" else metric
    samples_path = result / f"{prefix}_{component}_result.json"
    samples = json.loads(samples_path.read_text())  # Missing output is a failed evaluation.
    key = f"{page['document_id']}_page_{page['page']}-{page['page']}.jpg"
    selected = [sample for sample in samples if sample["img_id"] == key]
    if not selected:
        return None, "no_official_samples"
    if metric == "table_teds":
        values = [float(sample["metric"]["TEDS"]) for sample in selected]
        score = 100 * statistics.mean(values)
    else:
        scores = json.loads((result / f"{prefix}_{component}_per_page_edit.json").read_text())
        score = 100 * (1 - float(scores[key]))
    if not math.isfinite(score) or not -TOLERANCE <= score <= 100 + TOLERANCE:
        raise ValueError(f"Invalid official score for {page['id']}: {score}")
    return score, "evaluated"


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for metric in METRICS:
        paired = [r for r in rows if r[f"delta_{metric}"] is not None]
        deltas = [r[f"delta_{metric}"] for r in paired]
        losses = [r for r in paired if r[f"delta_{metric}"] < -TOLERANCE]
        mismatch = [r["id"] for r in rows if
                    (r[f"baseline_{metric}"] is None) != (r[f"candidate_{metric}"] is None)]
        summary[metric] = {
            "paired": len(paired), "selected": len(rows),
            "baseline": statistics.mean(r[f"baseline_{metric}"] for r in paired) if paired else None,
            "candidate": statistics.mean(r[f"candidate_{metric}"] for r in paired) if paired else None,
            "delta": statistics.mean(deltas) if deltas else None,
            "better": sum(d > TOLERANCE for d in deltas), "worse": len(losses),
            "equal": sum(abs(d) <= TOLERANCE for d in deltas),
            "regressions": [{"id": r["id"], "delta": r[f"delta_{metric}"]} for r in losses],
            "worst_delta": min(deltas) if deltas else None,
            "missing_baseline": [r["id"] for r in rows if r[f"baseline_{metric}"] is None],
            "missing_candidate": [r["id"] for r in rows if r[f"candidate_{metric}"] is None],
            "coverage_mismatch": mismatch,
        }
    if any(summary[m]["paired"] == 0 for m in ("reading_order", "text_block")):
        gate = "inconclusive"
    elif any(v["worse"] or v["coverage_mismatch"] for v in summary.values()):
        gate = "rejected"
    else:
        gate = "passed"
    return {"quality_gate": gate, "metrics": summary}


def make_report(root: Path) -> dict:
    pages = json.loads((root / "pages.json").read_text())
    for variant in ("baseline", "candidate"):
        check_inventory(root / variant / "fusion", pages)
    rows = []
    for page in pages:
        row = {k: page[k] for k in ("id", "subject", "document_id", "page", "batch")}
        for metric in METRICS:
            for variant in ("baseline", "candidate"):
                score, status = metric_score(root / variant / "result", f"batch-{page['batch']:02d}", metric, page)
                row[f"{variant}_{metric}"] = score
                row[f"{variant}_{metric}_status"] = status
            a, b = row[f"baseline_{metric}"], row[f"candidate_{metric}"]
            row[f"delta_{metric}"] = b - a if a is not None and b is not None else None
        row["markdown_changed"] = (
            (root / "baseline/fusion" / f"{page['id']}.drbench.md").read_bytes()
            != (root / "candidate/fusion" / f"{page['id']}.drbench.md").read_bytes()
        )
        rows.append(row)
    with (root / "per-page.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    summary["markdown_changed"] = sum(row["markdown_changed"] for row in rows)
    write_json(root / "summary.json", summary)
    lines = ["# Paired frozen replay", "", f"Quality gate: **{summary['quality_gate']}**.", "",
             "Scores are 0–100, higher is better; Δ = candidate − baseline. No Overall is calculated.", "",
             "| Metric | Paired/selected | Baseline | Candidate | Δ p.p. | Better/worse/equal |",
             "| --- | --- | --- | --- | --- | --- |"]
    for metric, value in summary["metrics"].items():
        fmt = lambda n: f"{n:.6f}" if n is not None else "—"
        lines.append(f"| {metric} | {value['paired']}/{value['selected']} | {fmt(value['baseline'])} "
                     f"| {fmt(value['candidate'])} | {fmt(value['delta'])} "
                     f"| {value['better']}/{value['worse']}/{value['equal']} |")
    lines += ["", "`table_teds` averages official table TEDS samples within each page before pairing.",
              "Missing scores retain `no_official_samples`; this is not a success or a zero score.",
              "Tables absent from both matched outputs need separate content checks.",
              "", "## Regressions and coverage", ""]
    for metric, value in summary["metrics"].items():
        for regression in value["regressions"]:
            lines.append(f"- {metric}: `{regression['id']}` {regression['delta']:+.6f} p.p.")
        if value["coverage_mismatch"]:
            lines.append(f"- {metric}: asymmetric metric coverage: {value['coverage_mismatch']}")
        if value["missing_baseline"] or value["missing_candidate"]:
            lines.append(f"- {metric}: missing baseline={value['missing_baseline']}; "
                         f"candidate={value['missing_candidate']}")
    lines += ["", "Reused development pages do not establish generalization. Per-page details, "
              "official outputs, decisions, commands, timings and source identities are preserved in this run."]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    return summary
