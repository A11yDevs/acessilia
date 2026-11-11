"""Score a predictions directory and compare two scored runs."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from pathlib import Path

from docstruct.evaluation.holdout import LOOP_METRICS, Verdict, evaluate_candidate
from docstruct.evaluation.markdown import score_markdown_page
from docstruct.evaluation.metrics import PageScores, overall_score

from scripts.bench.dataset_reference import git_revision
from scripts.bench.datasets import BenchPage
from scripts.bench.input_identity import INPUTS_FILE, check_input, run_inputs

REPORT_FILE = "report.json"
PAGES_FILE = "pages.jsonl"
DRILLDOWN_FILE = "drilldown.csv"
RUN_METADATA_FILE = "run-metadata.json"
SCORE_FILES = (REPORT_FILE, PAGES_FILE, DRILLDOWN_FILE, RUN_METADATA_FILE)
MANIFEST_FILE = "pages.txt"  # item ids a run covers, written by `run`
EXTRACTION_FILE = "extraction.json"  # run configuration, independent of scoring
PROTOCOL_VERSION = "drdocbench-markdown-v2"
COMPARISON_METRICS = (*LOOP_METRICS, "cdm")
IDENTITY_FIELDS = (
    "dataset", "dataset_revision", "reference_digest", "input_digest", "selection",
    "criterion_ids", "scope", "protocol_version", "output_mode",
)


def invalidate_scores(out: Path) -> None:
    for filename in SCORE_FILES:
        (out / filename).unlink(missing_ok=True)


def score_run(pages: list[BenchPage], predictions: Path, out: Path) -> dict:
    """Write ``report.json``, ``pages.jsonl`` and a worst-first ``drilldown.csv``.

    A page without ground truth is skipped; one without a prediction scores
    against an empty prediction, so a failed page counts as a miss.
    """
    invalidate_scores(out)
    rows: list[tuple[BenchPage, PageScores, str]] = []
    extraction_path = predictions.parent / EXTRACTION_FILE
    extraction = (
        json.loads(extraction_path.read_text(encoding="utf-8"))
        if extraction_path.is_file() else None
    )
    verify_inputs = (
        (predictions.parent / INPUTS_FILE).exists()
        or isinstance(extraction, dict) and extraction.get("input_identity_version") == 1
    )
    inputs = run_inputs(predictions.parent, required=verify_inputs)
    input_digest = None
    if verify_inputs:
        for page in pages:
            check_input(page, inputs)
        selected_inputs = {page.item_id: inputs[page.item_id] for page in pages}
        input_digest = hashlib.sha256(
            json.dumps(selected_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    reference_hash = hashlib.sha256()
    criteria_ids: list[str] = []
    unannotated = 0
    prediction_hash = hashlib.sha256()
    dataset_values = {
        page.meta.get("dataset_id") or page.meta.get("dataset") or "local"
        for page in pages
    }
    revision_values = {
        page.meta.get("dataset_revision") or page.meta.get("revision")
        for page in pages
    }
    if len(dataset_values) > 1:
        raise ValueError(f"a score run cannot mix Dataset identifiers: {sorted(dataset_values)}")
    if len(revision_values) > 1:
        raise ValueError(f"a score run cannot mix Dataset revisions: {sorted(map(str, revision_values))}")
    for page in pages:
        if page.gt_path is None:
            unannotated += 1
            continue
        pred_path = predictions / f"{page.item_id}.md"
        pred_bytes = pred_path.read_bytes() if pred_path.is_file() else None
        prediction_hash.update(page.item_id.encode("utf-8"))
        prediction_hash.update(pred_bytes if pred_bytes is not None else b"<missing>")
        pred = pred_bytes.decode("utf-8") if pred_bytes is not None else ""
        gt = page.gt_path.read_text(encoding="utf-8")
        reference_hash.update(page.item_id.encode("utf-8"))
        reference_hash.update(gt.encode("utf-8"))
        criteria_ids.append(page.item_id)
        rows.append((page, score_markdown_page(page.item_id, pred, gt), "present" if pred_bytes is not None else "missing_prediction"))

    report = overall_score([s for _, s, _ in rows])
    report["pages"] = len(rows)
    identity = {
        "protocol_version": PROTOCOL_VERSION,
        "dataset": next(iter(dataset_values), "local"),
        "dataset_revision": next(iter(revision_values), None),
        "reference_digest": reference_hash.hexdigest(),
        "input_digest": input_digest,
        "selection": sorted(criteria_ids),
        "criterion_ids": sorted(criteria_ids),
        "scope": "scored pages with available ground truth",
        "output_mode": "markdown",
    }
    report["evaluation_identity"] = identity
    report["unannotated_pages"] = unannotated
    report["prediction_digest"] = prediction_hash.hexdigest()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / PAGES_FILE, "w", encoding="utf-8") as fh:
        for page, s, artifact_status in rows:
            provenance_path = predictions / f"{page.item_id}.extraction.json"
            fh.write(json.dumps({
                "item_id": page.item_id,
                "document_id": page.document_id,
                "page": page.page,
                "criterion_id": page.item_id,
                "artifact_status": artifact_status,
                "evaluation_status": "evaluated" if artifact_status == "present" else "missing_artifact",
                "input": inputs.get(page.item_id),
                "extraction": (
                    json.loads(provenance_path.read_text(encoding="utf-8"))
                    if artifact_status == "present" and provenance_path.is_file() else None
                ),
                "overall": s.overall(),
                **_components(s),
            }) + "\n")
    with open(out / DRILLDOWN_FILE, "w", newline="", encoding="utf-8") as fh:
        fields = ["item_id", "overall", "text", "teds", "cdm", "reading_order"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        scored = [(p, s) for p, s, _status in rows if s.overall() is not None]
        for page, s in sorted(scored, key=lambda r: r[1].overall()):
            writer.writerow({"item_id": page.item_id, "overall": round(s.overall(), 2),
                             **{k: round(v, 2) for k, v in _components(s).items()}})
    (out / RUN_METADATA_FILE).write_text(json.dumps({
        "evaluation_identity": identity,
        "core_revision": git_revision(Path(__file__).resolve().parents[2]),
        "runtime": {"python": platform.python_version()},
        "configuration": {
            "predictions_directory": str(predictions.resolve()),
            "prediction_digest": prediction_hash.hexdigest(),
            "selected_criterion_ids": sorted(criteria_ids),
            "extraction": extraction,
            "prediction_inputs_verified": verify_inputs,
        },
        "unannotated_pages": unannotated,
        "missing_prediction_count": sum(status != "present" for _, _, status in rows),
        "artifacts": list(SCORE_FILES),
        "artifact_storage": {
            "directory": str(out.resolve()),
            "retention": "operator-managed; artifacts remain until explicitly removed",
            "observability_export": False,
        },
    }, indent=2) + "\n", encoding="utf-8")
    pending_report = out / f"{REPORT_FILE}.tmp"
    pending_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pending_report.replace(out / REPORT_FILE)
    return report


def _components(s: PageScores) -> dict[str, float]:
    """Components on 0–100, higher better (``text`` is 100 × (1 − text_ed))."""
    return {("text" if k == "text_ed" else k): v for k, v in s.components_0_100().items()}


def compare_runs(base: Path, candidate: Path) -> Verdict:
    """Tune/holdout acceptance (``docstruct.evaluation.holdout``) of two scored runs.

    Pages are keyed ``<document_id>_page_<N>`` so the split stays per document.
    """
    base_identity = _identity(base)
    candidate_identity = _identity(candidate)
    mismatches = [key for key in IDENTITY_FIELDS if base_identity[key] != candidate_identity[key]]
    if mismatches:
        raise ValueError(
            "incomparable benchmark runs; evaluation identity differs for: "
            + ", ".join(mismatches)
        )
    criteria = set(base_identity["criterion_ids"])
    base_windows = _windows(base, criteria)
    candidate_windows = _windows(candidate, criteria)
    base_pages = {score["criterion_id"]: key for key, score in base_windows.items()}
    candidate_pages = {score["criterion_id"]: key for key, score in candidate_windows.items()}
    if base_pages != candidate_pages:
        raise ValueError("incomparable benchmark runs; criteria identify different pages")
    for key, base_score in base_windows.items():
        candidate_score = candidate_windows[key]
        for metric in ("teds", "cdm"):
            if (base_score[metric] is None) != (candidate_score[metric] is None):
                raise ValueError(f"incomparable benchmark runs; {metric} coverage differs for {key}")
    return evaluate_candidate(base_windows, candidate_windows, metrics=COMPARISON_METRICS)


def _identity(run: Path) -> dict:
    report_path = run / REPORT_FILE
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"incomparable benchmark run {run}: evaluation identity is missing or invalid; rescore it with the current protocol"
        ) from exc
    identity = report.get("evaluation_identity") if isinstance(report, dict) else None
    if not isinstance(identity, dict) or not set(IDENTITY_FIELDS) <= identity.keys():
        raise ValueError(
            f"incomparable benchmark run {run}: evaluation identity is incomplete; rescore it with the current protocol"
        )
    if identity["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError(
            f"incomparable benchmark run {run}: unsupported evaluation protocol; rescore it with {PROTOCOL_VERSION}"
        )
    input_digest = identity["input_digest"]
    if input_digest is None:
        raise ValueError(
            f"incomparable benchmark run {run}: prediction inputs were not verified; "
            "rerun extraction and scoring to record input identities"
        )
    criteria = identity["criterion_ids"]
    digest = identity["reference_digest"]
    if (
        not isinstance(criteria, list)
        or not all(isinstance(criterion, str) and criterion for criterion in criteria)
        or len(set(criteria)) != len(criteria)
        or identity["selection"] != criteria
        or not isinstance(digest, str)
        or not digest
        or not isinstance(input_digest, str)
        or len(input_digest) != 64
        or any(char not in "0123456789abcdef" for char in input_digest)
    ):
        raise ValueError(
            f"incomparable benchmark run {run}: evaluation identity is invalid; rescore it with the current protocol"
        )
    return identity


def _windows(run: Path, criteria: set[str]) -> dict[str, dict]:
    path = run / PAGES_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read benchmark scores in {path}: {exc}") from exc
    pending = criteria.copy()
    windows = {}
    for line_number, line in enumerate(lines, start=1):
        row = json.loads(line)
        criterion = row.get("criterion_id") if isinstance(row, dict) else None
        if not isinstance(criterion, str) or row.get("item_id") != criterion or criterion not in criteria:
            raise ValueError(f"{path}:{line_number}: invalid or unexpected criterion {criterion!r}")
        if criterion not in pending:
            raise ValueError(f"{path}:{line_number}: duplicate criterion {criterion!r}")
        document, page = row.get("document_id"), row.get("page")
        if not isinstance(document, str) or not document or type(page) is not int:
            raise ValueError(f"{path}:{line_number}: invalid document or page for {criterion!r}")
        key = f"{document}_page_{page}"
        if key in windows:
            raise ValueError(f"{path}:{line_number}: duplicate score for page {key!r}")
        pending.remove(criterion)
        windows[key] = {
            "criterion_id": criterion,
            "text": row.get("text"),
            "reading_order": row.get("reading_order"),
            "teds": row.get("teds"),
            "cdm": row.get("cdm"),
        }
    if pending:
        raise ValueError(f"{path}: missing criteria {sorted(pending)}")
    return windows
