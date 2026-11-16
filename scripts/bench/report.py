"""Score local benchmark runs and compare compatible results."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from docstruct.evaluation import holdout as holdout_module
from docstruct.evaluation import markdown as markdown_module
from docstruct.evaluation import metrics as metrics_module
from docstruct.evaluation.holdout import (
    LOOP_METRICS,
    MAX_METRIC_LOSS,
    MIN_HOLDOUT_GAIN,
    MIN_TUNE_GAIN,
    Verdict,
    evaluate_candidate,
    score as holdout_score,
)
from docstruct.evaluation.markdown import score_markdown_page
from docstruct.evaluation.metrics import PageScores, overall_score

from scripts.bench.datasets import BenchPage
from scripts.bench.run_manifest import (
    RUN_MANIFEST_FILE,
    atomic_write_json,
    completed_artifacts_are_valid,
    digest,
    is_pinned_revision,
    load_run_manifest,
    selection_snapshot,
    sha256_file,
)

PAGES_FILE = "pages.jsonl"
SELECTION_IDS_FILE = "pages.txt"  # compatibility list; run-manifest.json is authoritative
SCORING_PROTOCOL = {
    "id": "acessilia-docstruct-local-page-metrics",
    "version": 1,
    "implementation": "docstruct.evaluation.markdown.score_markdown_page",
    "metrics": ["text", "reading_order", "teds", "cdm"],
    "scale": "0-100, higher is better",
    "official_evaluator": False,
}
GATE_PROTOCOL = {
    "id": "docstruct.evaluation.holdout.improvement",
    "kind": "improvement",
    "version": 1,
    "metrics": list(LOOP_METRICS),
    "minimum_tune_gain": MIN_TUNE_GAIN,
    "minimum_holdout_gain": MIN_HOLDOUT_GAIN,
    "maximum_metric_loss": MAX_METRIC_LOSS,
    "cdm_in_gate": False,
}
ALL_METRICS = ("text", "reading_order", "teds", "cdm")
SCORE_ARTIFACTS = ("report.json", PAGES_FILE, "drilldown.csv", "comparison.json")


def invalidate_score_artifacts(run_dir: Path) -> None:
    """Remove scores and verdicts when a run's predictions may have changed."""
    for name in SCORE_ARTIFACTS:
        (run_dir / name).unlink(missing_ok=True)


def score_run(pages: list[BenchPage], predictions: Path, out: Path) -> dict:
    """Write local score files and persist their identity and coverage.

    A page without ground truth is not scorable. A page with ground truth but
    without a prediction is scored as an empty prediction and counts as a miss.
    """
    out.mkdir(parents=True, exist_ok=True)
    invalidate_score_artifacts(out)
    rows: list[tuple[BenchPage, PageScores]] = []
    for page in pages:
        if page.gt_path is None:
            continue
        pred_path = predictions / f"{page.item_id}.md"
        pred = pred_path.read_text(encoding="utf-8") if pred_path.exists() else ""
        gt = page.gt_path.read_text(encoding="utf-8")
        rows.append((page, score_markdown_page(page.item_id, pred, gt)))

    score = overall_score([page_score for _, page_score in rows])
    score["pages"] = len(rows)
    manifest, manifest_error = _load_manifest(predictions.parent)
    manifest_items = manifest.get("items", {}) if manifest else {}
    if not isinstance(manifest_items, dict):
        manifest_items = {}
    manifest_selection = manifest.get("selection") if manifest else None
    selection_items = (
        manifest_selection.get("items")
        if isinstance(manifest_selection, dict)
        and isinstance(manifest_selection.get("items"), list)
        else None
    )
    expected_descriptors = selection_items or [
        {"item_id": page.item_id, "reference_sha256": "present" if page.gt_path else None}
        for page in pages
    ]
    expected_ids = [item["item_id"] for item in expected_descriptors]
    expected_reference_ids = [
        item["item_id"] for item in expected_descriptors if item.get("reference_sha256")
    ]
    page_ids = {page.item_id for page in pages}
    reference_ids = [page.item_id for page, _ in rows]
    try:
        current_selection = selection_snapshot(pages)
        selection_matches = (
            not manifest
            or current_selection.get("sha256") == _selection_hash(manifest, "sha256")
        )
        current_selection_hash = current_selection.get("sha256")
    except (OSError, ValueError) as exc:
        selection_matches = False if manifest else None
        current_selection_hash = None
        manifest_error = manifest_error or type(exc).__name__
    missing_input_ids = sorted(set(expected_ids) - page_ids)
    missing_reference_ids = sorted(set(expected_reference_ids) - set(reference_ids))
    unexpected_ids = sorted(page_ids - set(expected_ids))
    executed_ids = sorted(
        item_id for item_id, status in manifest_items.items()
        if isinstance(status, dict) and status.get("status") == "completed"
    )
    status_counts: dict[str, int] = {}
    for status in manifest_items.values():
        name = status.get("status", "unknown") if isinstance(status, dict) else "unknown"
        status_counts[name] = status_counts.get(name, 0) + 1
    component_ids = {metric: [] for metric in ALL_METRICS}
    failed_ids = [
        item_id for item_id, state in manifest_items.items()
        if isinstance(state, dict) and state.get("status") in {"failed", "cancelled"}
    ]

    pages_path = out / PAGES_FILE
    with pages_path.open("w", encoding="utf-8") as fh:
        for page, page_score in rows:
            components = _components(page_score)
            for metric in ALL_METRICS:
                if _is_scorable(components.get(metric)):
                    component_ids[metric].append(page.item_id)
            fh.write(json.dumps(json_safe({
                "item_id": page.item_id,
                "document_id": page.document_id,
                "page": page.page,
                "overall": page_score.overall(),
                **components,
            }), ensure_ascii=False, allow_nan=False) + "\n")

    fields = ["item_id", "overall", *ALL_METRICS]
    with (out / "drilldown.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        scorable = [(page, page_score) for page, page_score in rows
                    if _is_scorable(page_score.overall())]
        for page, page_score in sorted(scorable, key=lambda row: row[1].overall()):
            writer.writerow({
                "item_id": page.item_id,
                "overall": round(page_score.overall(), 2),
                **{
                    key: round(value, 2) if _is_scorable(value) else ""
                    for key, value in _components(page_score).items()
                },
            })

    score["measurement"] = {
        "kind": "local_approximation",
        "protocol": _current_scoring_protocol(),
        "official_evaluator": False,
        "gate": GATE_PROTOCOL,
    }
    score["run_identity"] = {
        "manifest_file": RUN_MANIFEST_FILE,
        "run_id": manifest.get("run_id") if manifest else None,
        "identity_sha256": manifest.get("identity_sha256") if manifest else None,
        "selection_sha256": _selection_hash(manifest, "sha256") if manifest else None,
        "references_sha256": (
            _selection_hash(manifest, "references_sha256") if manifest else None
        ),
        "current_selection_sha256": current_selection_hash,
        "selection_matches_manifest": selection_matches,
        "manifest_status": manifest.get("status") if manifest else "missing",
        "manifest_error": manifest_error,
    }
    score["coverage"] = {
        "expected_pages": len(expected_ids),
        "expected_item_ids": expected_ids,
        "expected_reference_item_ids": expected_reference_ids,
        "scored_reference_item_ids": reference_ids,
        "missing_input_item_ids": missing_input_ids,
        "missing_reference_item_ids": missing_reference_ids,
        "unexpected_item_ids": unexpected_ids,
        "executed_pages": len(executed_ids) if manifest else None,
        "executed_item_ids": executed_ids if manifest else None,
        "failed_pages": len(failed_ids) if manifest else None,
        "failed_item_ids": sorted(failed_ids) if manifest else None,
        "not_completed_pages": len(set(expected_ids) - set(executed_ids)) if manifest else None,
        "item_status_counts": status_counts if manifest else None,
        "scorable_reference_pages": len(reference_ids),
        "scorable_by_metric": {
            metric: {
                "expected": len(expected_reference_ids),
                "scorable": len(component_ids[metric]),
                "item_ids": component_ids[metric],
            }
            for metric in ALL_METRICS
        },
    }
    score["score_artifacts"] = {"pages_jsonl_sha256": sha256_file(pages_path)}
    atomic_write_json(out / "report.json", json_safe(score))
    return score


def _components(page_score: PageScores) -> dict[str, float | None]:
    """Components on 0–100, higher better (``text`` is 100 × (1 − text_ed))."""
    return {
        ("text" if key == "text_ed" else key): value
        for key, value in page_score.components_0_100().items()
    }


def _is_scorable(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _module_sha256(module) -> str | None:
    path = getattr(module, "__file__", None)
    if not path:
        return None
    try:
        return sha256_file(Path(path))
    except OSError:
        return None


def _current_scoring_protocol() -> dict:
    try:
        implementation_version = version("acessilia-docstruct")
    except PackageNotFoundError:
        implementation_version = "unknown"
    return {
        **SCORING_PROTOCOL,
        "implementation_version": implementation_version,
        "implementation_sha256": {
            "markdown": _module_sha256(markdown_module),
            "metrics": _module_sha256(metrics_module),
            "holdout": _module_sha256(holdout_module),
        },
    }


def compare_runs(base: Path, candidate: Path) -> Verdict:
    """Return the local improvement-gate verdict, rejecting incompatible runs."""
    return _verdict_from_report(compare_run_report(base, candidate))


def compare_run_report(base: Path, candidate: Path) -> dict:
    """Build a durable compatibility and improvement report for two runs."""
    base_manifest, base_error = _load_manifest(base)
    candidate_manifest, candidate_error = _load_manifest(candidate)
    base_report = _load_score_report(base)
    candidate_report = _load_score_report(candidate)
    base_windows, base_rows, base_row_issues = _read_windows(base)
    candidate_windows, candidate_rows, candidate_row_issues = _read_windows(candidate)

    issues = [
        *base_row_issues,
        *candidate_row_issues,
        *_manifest_issues("base", base, base_manifest, base_error),
        *_manifest_issues("candidate", candidate, candidate_manifest, candidate_error),
        *_report_issues("base", base_report, base_manifest),
        *_report_issues("candidate", candidate_report, candidate_manifest),
    ]
    issues.extend(_identity_pair_issues(base_manifest, candidate_manifest))
    issues.extend(_coverage_pair_issues(base_report, candidate_report, base_rows, candidate_rows))

    verdict = evaluate_candidate(base_windows, candidate_windows)
    accepted = verdict.accepted and not issues
    reason_parts = []
    if issues:
        reason_parts.append("incompatible runs: " + "; ".join(_unique(issues)))
    if not verdict.accepted:
        reason_parts.append(verdict.reason)
    reason = "; ".join(reason_parts) if reason_parts else verdict.reason
    final_verdict = Verdict(
        accepted=accepted,
        reason=reason,
        tune_delta=verdict.tune_delta,
        holdout_delta=verdict.holdout_delta,
        metric_deltas=verdict.metric_deltas,
    )

    diagnostic_deltas = _diagnostic_deltas(base_windows, candidate_windows)
    report = {
        "schema": "acessilia-benchmark-comparison",
        "schema_version": 1,
        "measurement": {
            "kind": "local_approximation",
            "official_evaluator": False,
            "gate": GATE_PROTOCOL,
        },
        "compatibility": {"compatible": not issues, "issues": _unique(issues)},
        "environment_differences": {
            field: (
                digest(base_manifest.get(field)) != digest(candidate_manifest.get(field))
                if base_manifest is not None and candidate_manifest is not None
                else None
            )
            for field in ("configuration", "software", "hardware")
        },
        "runs": {
            "base": _run_summary(base, base_manifest, base_report),
            "candidate": _run_summary(candidate, candidate_manifest, candidate_report),
        },
        "diagnostic_metric_deltas": diagnostic_deltas,
        "verdict": {
            "accepted": final_verdict.accepted,
            "reason": final_verdict.reason,
            "tune_delta": final_verdict.tune_delta,
            "holdout_delta": final_verdict.holdout_delta,
            "metric_deltas": final_verdict.metric_deltas,
        },
    }
    return json_safe(report)


def _load_manifest(run: Path) -> tuple[dict | None, str | None]:
    try:
        return load_run_manifest(run), None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, type(exc).__name__


def _load_score_report(run: Path) -> dict | None:
    try:
        report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return report if isinstance(report, dict) else None


def _manifest_issues(
    label: str, run: Path, manifest: dict | None, error: str | None
) -> list[str]:
    if manifest is None:
        return [f"{label} run manifest missing or invalid ({error or 'missing'})"]
    issues = []
    if manifest.get("status") != "completed":
        issues.append(f"{label} run status is {manifest.get('status', 'unknown')}")
    selection = manifest.get("selection")
    selected = selection.get("items") if isinstance(selection, dict) else None
    items = manifest.get("items")
    if not isinstance(selected, list) or not isinstance(items, dict):
        return [*issues, f"{label} run manifest has invalid item coverage"]
    selected_ids = [item.get("item_id") for item in selected if isinstance(item, dict)]
    valid_ids = [item_id for item_id in selected_ids if isinstance(item_id, str)]
    if (
        len(selected_ids) != len(selected)
        or len(valid_ids) != len(selected_ids)
        or len(valid_ids) != len(set(valid_ids))
    ):
        issues.append(f"{label} run manifest has duplicate or invalid selection ids")
    if set(valid_ids) != set(items):
        issues.append(f"{label} run manifest item states do not match its selection")
    predictions = run / "predictions"
    require_raw_payload = bool(
        manifest.get("configuration", {}).get("raw_payload_saved")
        if isinstance(manifest.get("configuration"), dict)
        else False
    )
    for item_id in valid_ids:
        state = items.get(item_id)
        if not isinstance(state, dict) or not completed_artifacts_are_valid(
            predictions, state, item_id, require_raw_payload=require_raw_payload
        ):
            issues.append(f"{label} item {item_id} is incomplete or has invalid artifacts")
    return issues


def _report_issues(label: str, report: dict | None, manifest: dict | None) -> list[str]:
    if report is None:
        return [f"{label} score report missing or invalid"]
    if manifest is None:
        return []
    identity = report.get("run_identity")
    if not isinstance(identity, dict) or identity.get("run_id") != manifest.get("run_id"):
        return [f"{label} score report does not identify its run manifest"]
    if (
        identity.get("identity_sha256") != manifest.get("identity_sha256")
        or identity.get("selection_sha256") != _selection_hash(manifest, "sha256")
        or identity.get("references_sha256") != _selection_hash(manifest, "references_sha256")
    ):
        return [f"{label} score identity differs from its run manifest"]
    measurement = report.get("measurement")
    protocol = measurement.get("protocol") if isinstance(measurement, dict) else None
    gate = measurement.get("gate") if isinstance(measurement, dict) else None
    if (
        not isinstance(protocol, dict)
        or protocol.get("official_evaluator") is not False
        or not isinstance(gate, dict)
    ):
        return [f"{label} score report has no recognized local evaluator protocol"]
    issues = []
    if digest(protocol) != digest(_current_scoring_protocol()):
        issues.append(f"{label} scoring protocol differs from the current evaluator")
    if digest(gate) != digest(GATE_PROTOCOL):
        issues.append(f"{label} acceptance gate differs from the current gate")
    score_artifacts = report.get("score_artifacts")
    pages_hash = score_artifacts.get("pages_jsonl_sha256") if isinstance(score_artifacts, dict) else None
    try:
        pages_hash_matches = isinstance(pages_hash, str) and sha256_file(run / PAGES_FILE) == pages_hash
    except OSError:
        pages_hash_matches = False
    if not pages_hash_matches:
        issues.append(f"{label} score rows do not match the score report")
    if identity.get("selection_matches_manifest") is not True:
        issues.append(f"{label} score inputs do not match the run manifest")
    selection = manifest.get("selection")
    descriptors = selection.get("items") if isinstance(selection, dict) else None
    if isinstance(descriptors, list):
        expected_ids = [item.get("item_id") for item in descriptors if isinstance(item, dict)]
        expected_reference_ids = [
            item.get("item_id") for item in descriptors
            if isinstance(item, dict) and item.get("reference_sha256")
        ]
        coverage = report.get("coverage")
        if not isinstance(coverage, dict):
            issues.append(f"{label} score report has no coverage metadata")
        else:
            if coverage.get("expected_item_ids") != expected_ids:
                issues.append(f"{label} score selection differs from its run manifest")
            if coverage.get("expected_reference_item_ids") != expected_reference_ids:
                issues.append(f"{label} score references differ from its run manifest")
            for key in ("missing_input_item_ids", "missing_reference_item_ids", "unexpected_item_ids"):
                if coverage.get(key):
                    issues.append(f"{label} score coverage has {key.replace('_', ' ')}")
    return issues


def _identity_pair_issues(base: dict | None, candidate: dict | None) -> list[str]:
    if base is None or candidate is None:
        return []
    issues = []
    base_dataset = base.get("dataset") if isinstance(base.get("dataset"), dict) else {}
    candidate_dataset = (
        candidate.get("dataset") if isinstance(candidate.get("dataset"), dict) else {}
    )
    for name in ("name", "split", "revision"):
        if base_dataset.get(name) != candidate_dataset.get(name):
            issues.append(f"dataset {name} differs")
    for label, dataset in (("base", base_dataset), ("candidate", candidate_dataset)):
        revision = dataset.get("revision")
        if (
            not is_pinned_revision(revision)
            or dataset.get("revision_source") not in {"explicit", "git_checkout"}
        ):
            issues.append(f"{label} dataset revision is unavailable")
    for label, left, right in (
        ("unit/protocol", base.get("protocol"), candidate.get("protocol")),
        ("selection", _selection_hash(base, "sha256"), _selection_hash(candidate, "sha256")),
        (
            "references",
            _selection_hash(base, "references_sha256"),
            _selection_hash(candidate, "references_sha256"),
        ),
    ):
        if digest(left) != digest(right):
            issues.append(f"{label} differs")
    return issues


def _selection_hash(manifest: dict, key: str):
    selection = manifest.get("selection")
    return selection.get(key) if isinstance(selection, dict) else None


def _coverage_pair_issues(
    base_report: dict | None,
    candidate_report: dict | None,
    base_rows: list[dict],
    candidate_rows: list[dict],
) -> list[str]:
    issues = []
    base_coverage = base_report.get("coverage") if base_report else None
    candidate_coverage = candidate_report.get("coverage") if candidate_report else None
    if not isinstance(base_coverage, dict) or not isinstance(candidate_coverage, dict):
        issues.append("score coverage metadata missing")
    else:
        for key in (
            "expected_pages",
            "executed_pages",
            "failed_pages",
            "not_completed_pages",
            "scorable_reference_pages",
        ):
            left_count = base_coverage.get(key)
            right_count = candidate_coverage.get(key)
            if not _is_nonnegative_int(left_count) or not _is_nonnegative_int(right_count):
                issues.append(f"{key.replace('_', ' ')} is invalid")
            elif left_count != right_count:
                issues.append(f"{key.replace('_', ' ')} differs")
        for key in (
            "expected_item_ids",
            "expected_reference_item_ids",
            "scored_reference_item_ids",
        ):
            left = _coverage_id_set(base_coverage, key)
            right = _coverage_id_set(candidate_coverage, key)
            if left is None or right is None:
                issues.append(f"{key.replace('_', ' ')} is invalid")
            elif left != right:
                issues.append(f"{key.replace('_', ' ')} differs")
        left_measurement = base_report.get("measurement") if base_report else None
        right_measurement = candidate_report.get("measurement") if candidate_report else None
        left_eval = left_measurement.get("protocol") if isinstance(left_measurement, dict) else None
        right_eval = right_measurement.get("protocol") if isinstance(right_measurement, dict) else None
        if digest(left_eval) != digest(right_eval):
            issues.append("evaluation protocol differs")
        left_gate = left_measurement.get("gate") if isinstance(left_measurement, dict) else None
        right_gate = right_measurement.get("gate") if isinstance(right_measurement, dict) else None
        if digest(left_gate) != digest(right_gate):
            issues.append("acceptance gate differs")
    left_ids = {metric: _scorable_ids(base_rows, metric) for metric in ALL_METRICS}
    right_ids = {metric: _scorable_ids(candidate_rows, metric) for metric in ALL_METRICS}
    for metric in ALL_METRICS:
        if left_ids[metric] != right_ids[metric]:
            issues.append(f"{metric} scorable coverage differs")
    if isinstance(base_coverage, dict) and isinstance(candidate_coverage, dict):
        left_recorded = base_coverage.get("scorable_by_metric", {})
        right_recorded = candidate_coverage.get("scorable_by_metric", {})
        expected_reference_ids = _coverage_id_set(
            base_coverage, "expected_reference_item_ids"
        )
        expected_reference_count = (
            len(expected_reference_ids) if expected_reference_ids is not None else None
        )
        for metric in ALL_METRICS:
            left_metric = left_recorded.get(metric) if isinstance(left_recorded, dict) else None
            right_metric = right_recorded.get(metric) if isinstance(right_recorded, dict) else None
            left_recorded_ids = _ids_for_metric(left_recorded, metric)
            right_recorded_ids = _ids_for_metric(right_recorded, metric)
            if (
                left_recorded_ids is None
                or right_recorded_ids is None
                or left_recorded_ids != left_ids[metric]
                or right_recorded_ids != right_ids[metric]
                or not isinstance(left_metric, dict)
                or not isinstance(right_metric, dict)
                or not _is_nonnegative_int(left_metric.get("expected"))
                or not _is_nonnegative_int(right_metric.get("expected"))
                or not _is_nonnegative_int(left_metric.get("scorable"))
                or not _is_nonnegative_int(right_metric.get("scorable"))
                or left_metric.get("expected") != expected_reference_count
                or right_metric.get("expected") != expected_reference_count
                or left_metric.get("scorable") != len(left_ids[metric])
                or right_metric.get("scorable") != len(right_ids[metric])
            ):
                issues.append(f"{metric} score rows do not match recorded coverage")
    return issues


def _read_windows(run: Path) -> tuple[dict[str, dict], list[dict], list[str]]:
    path = run / PAGES_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}, [], [f"{run.name} {PAGES_FILE} missing"]
    windows: dict[str, dict] = {}
    rows: list[dict] = []
    issues = []
    item_ids: set[str] = set()
    window_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
            item_id = row["item_id"]
            document_id = row["document_id"]
            page = row["page"]
            if (
                not isinstance(item_id, str)
                or not item_id
                or not isinstance(document_id, str)
                or not document_id
                or not isinstance(page, int)
                or isinstance(page, bool)
                or page < 1
            ):
                raise ValueError("invalid item identity")
            for metric in ALL_METRICS:
                value = row.get(metric)
                if value is not None and (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                ):
                    raise ValueError("invalid metric value")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            issues.append(f"{run.name} {PAGES_FILE} has an invalid row at line {line_number}")
            continue
        window_id = f"{document_id}_page_{page}"
        if item_id in item_ids or window_id in window_ids:
            issues.append(f"{run.name} {PAGES_FILE} has duplicate item/page ids")
            continue
        item_ids.add(item_id)
        window_ids.add(window_id)
        rows.append(row)
        windows[window_id] = {metric: row.get(metric) for metric in ALL_METRICS}
    return windows, rows, issues


def _scorable_ids(rows: list[dict], metric: str) -> set[str]:
    return {row["item_id"] for row in rows if row.get(metric) is not None}


def _coverage_id_set(coverage: dict, key: str) -> set[str] | None:
    value = coverage.get(key) if isinstance(coverage, dict) else None
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        return None
    return set(value)


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _ids_for_metric(coverage: dict, metric: str) -> set[str] | None:
    value = coverage.get(metric) if isinstance(coverage, dict) else None
    ids = value.get("item_ids") if isinstance(value, dict) else None
    if (
        not isinstance(ids, list)
        or any(not isinstance(item, str) or not item for item in ids)
        or len(ids) != len(set(ids))
    ):
        return None
    return set(ids)


def _diagnostic_deltas(base: dict[str, dict], candidate: dict[str, dict]) -> dict:
    result = {}
    for metric in ALL_METRICS:
        base_tune = holdout_score(base, "tune", (metric,))[metric]
        candidate_tune = holdout_score(candidate, "tune", (metric,))[metric]
        base_hold = holdout_score(base, "hold", (metric,))[metric]
        candidate_hold = holdout_score(candidate, "hold", (metric,))[metric]
        result[metric] = {
            "tune": candidate_tune - base_tune,
            "hold": candidate_hold - base_hold,
        }
    return result


def _run_summary(run: Path, manifest: dict | None, report: dict | None) -> dict:
    coverage = report.get("coverage") if report else None
    return {
        "path": run.name,
        "dataset": manifest.get("dataset") if manifest else None,
        "run_id": manifest.get("run_id") if manifest else None,
        "identity_sha256": manifest.get("identity_sha256") if manifest else None,
        "status": manifest.get("status") if manifest else "missing",
        "selection_sha256": _selection_hash(manifest, "sha256") if manifest else None,
        "references_sha256": _selection_hash(manifest, "references_sha256") if manifest else None,
        "protocol": manifest.get("protocol") if manifest else None,
        "configuration": manifest.get("configuration") if manifest else None,
        "software": manifest.get("software") if manifest else None,
        "hardware": manifest.get("hardware") if manifest else None,
        "coverage": coverage,
    }


def _verdict_from_report(report: dict) -> Verdict:
    value = report["verdict"]
    return Verdict(
        accepted=value["accepted"],
        reason=value["reason"],
        tune_delta=_restore_nonfinite(value["tune_delta"]),
        holdout_delta=_restore_nonfinite(value["holdout_delta"]),
        metric_deltas={
            key: _restore_nonfinite(number)
            for key, number in value["metric_deltas"].items()
        },
    )


def _restore_nonfinite(value):
    return float("nan") if value is None else value


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def json_safe(value):
    """Convert non-finite numbers to ``null`` for strict JSON output."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value
