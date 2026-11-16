"""Benchmark harness CLI.

    python -m scripts.bench download --dataset drdocbench --split dev --limit 50
    python -m scripts.bench run      --dataset drdocbench --split dev --sample 10
    python -m scripts.bench score    --dataset drdocbench --split dev
    python -m scripts.bench compare  var/bench/drdocbench/dev/<base> var/bench/drdocbench/dev/<candidate>
    python -m scripts.bench submit   --dataset drdocbench --split test

Data lives in ``$BENCH_VAR/<dataset>/<split>/data`` (``--root`` to override);
each run in ``$BENCH_VAR/<dataset>/<split>/<run>`` (``--run``, default ``latest``).
``BENCH_VAR`` defaults to ``var/bench`` in the repository.
Scores are local approximations for tracking deltas; use the benchmark's
official evaluator for reported numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

from docstruct.export.markdown import document_to_markdown

from scripts.bench import core, toolbox
from scripts.bench.datasets import DATASETS
from scripts.bench.report import (
    SELECTION_IDS_FILE,
    compare_run_report,
    invalidate_score_artifacts,
    score_run,
)
from scripts.bench.run_manifest import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    build_run_manifest,
    completed_artifacts_are_valid,
    is_pinned_revision,
    load_run_manifest,
    sha256_file,
    utc_now,
    write_run_manifest,
)

VAR = Path(os.environ.get("BENCH_VAR") or Path(__file__).resolve().parents[2] / "var" / "bench")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.bench", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def dataset_command(name: str, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--dataset", required=True, choices=sorted(DATASETS))
        p.add_argument("--split", default="dev")
        p.add_argument("--root", type=Path, help="local dataset tree")
        p.add_argument("--run", default="latest", help="run name (predictions and scores)")
        return p

    p = dataset_command("download", "materialize a split as a local tree")
    p.add_argument("--limit", type=int)
    p = dataset_command("run", "run Toolbox structure extraction on pages and write predictions")
    p.add_argument("--sample", type=int, help="first N pages only")
    p.add_argument("--item", help="a single item id")
    p.add_argument("--provider", help="Toolbox structure provider override")
    p.add_argument(
        "--dataset-revision",
        help="full source commit SHA for a materialized tree without Git metadata",
    )
    p.add_argument("--save-raw", action="store_true", help="also keep the Toolbox payload")
    p.add_argument("--resume", action="store_true", help="resume a compatible run with verified artifacts")
    dataset_command("score", "score a run against the ground truth")
    dataset_command("submit", "package a run in the benchmark's submission format")
    p = sub.add_parser("compare", help="tune/holdout acceptance of a candidate run")
    p.add_argument("base", type=Path)
    p.add_argument("candidate", type=Path)

    args = parser.parse_args(argv)
    if args.command == "run" and args.dataset_revision is not None:
        args.dataset_revision = args.dataset_revision.strip()
        if not is_pinned_revision(args.dataset_revision):
            parser.error("--dataset-revision must be a full commit SHA")
    if args.command == "compare":
        report = compare_run_report(args.base, args.candidate)
        atomic_write_json(args.candidate / "comparison.json", report)
        verdict = report["verdict"]
        print(json.dumps(_finite(verdict), indent=2, allow_nan=False))
        return 0 if verdict["accepted"] else 1

    if not _is_path_segment(args.split):
        parser.error("--split must be a single directory name")
    if hasattr(args, "run") and not _is_path_segment(args.run):
        parser.error("--run must be a single directory name")

    dataset = DATASETS[args.dataset]
    root = args.root or VAR / args.dataset / args.split / "data"
    run_dir = VAR / args.dataset / args.split / args.run
    predictions = run_dir / "predictions"

    if args.command == "download":
        print(f"{dataset.download(args.split, root, args.limit)} pages written to {root}")
        return 0

    pages = dataset.pages(root)
    if not pages:
        print(f"No pages under {root}; run `download` first or pass --root", file=sys.stderr)
        return 1

    if args.command == "run":
        if args.item:
            pages = [p for p in pages if p.item_id == args.item]
        if args.sample is not None:
            if args.sample < 1:
                parser.error("--sample must be at least 1")
            pages = pages[: args.sample]
        return _run(
            pages,
            run_dir,
            args.provider,
            args.save_raw,
            dataset=args.dataset,
            split=args.split,
            root=root,
            resume=args.resume,
            dataset_revision=args.dataset_revision,
        )
    if args.command == "score":
        try:
            run_manifest = load_run_manifest(run_dir)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Invalid run manifest ({type(exc).__name__}) in {run_dir}", file=sys.stderr)
            return 1
        if run_manifest is not None:
            selection = run_manifest.get("selection", {}).get("items", [])
            selected = {item.get("item_id") for item in selection if isinstance(item, dict)}
            pages = [p for p in pages if p.item_id in selected]
        else:
            manifest = run_dir / SELECTION_IDS_FILE
            if manifest.exists():
                selected = set(manifest.read_text(encoding="utf-8").split())
                pages = [p for p in pages if p.item_id in selected]
        report = score_run(pages, predictions, run_dir)
        print(json.dumps(_finite(report), indent=2, allow_nan=False))
        if not report["pages"]:
            print(f"No page of the run has ground truth under {root}", file=sys.stderr)
            return 1
        return 0
    zip_path = dataset.build_submission(pages, predictions, run_dir / "submission")
    print(f"Submission ready: {zip_path}")
    return 0


def _run(
    selected,
    run_dir: Path,
    provider: str | None,
    save_raw: bool,
    *,
    dataset: str,
    split: str,
    root: Path,
    resume: bool = False,
    dataset_revision: str | None = None,
) -> int:
    predictions = run_dir / "predictions"
    if not selected:
        print("No pages selected", file=sys.stderr)
        return 1

    run_dir.mkdir(parents=True, exist_ok=True)
    expected = build_run_manifest(
        dataset=dataset,
        split=split,
        run_name=run_dir.name,
        pages=selected,
        provider=provider,
        save_raw=save_raw,
        root=root,
        dataset_revision=dataset_revision,
    )
    legacy_ids: set[str] = set()
    if resume:
        try:
            manifest = load_run_manifest(run_dir)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Cannot resume invalid run manifest ({type(exc).__name__})", file=sys.stderr)
            return 1
        if manifest is not None:
            if manifest.get("identity_sha256") != expected["identity_sha256"]:
                print(
                    "Cannot resume: dataset, selection, source, software, hardware or "
                    "effective configuration differs from the saved run",
                    file=sys.stderr,
                )
                return 1
            expected_ids = set(expected["items"])
            if set(manifest.get("items", {})) != expected_ids:
                print("Cannot resume: saved item states do not match the selection", file=sys.stderr)
                return 1
            for page in selected:
                item = manifest["items"][page.item_id]
                if item.get("status") == "completed" and not completed_artifacts_are_valid(
                    predictions,
                    item,
                    page.item_id,
                    require_raw_payload=bool(expected["configuration"]["raw_payload_saved"]),
                ):
                    _remove_item_artifacts(predictions, item, page.item_id)
                    item.update(status="not_executed", artifacts={})
                elif item.get("status") == "legacy_unverified":
                    legacy_ids.add(page.item_id)
        else:
            previous_ids = _manifest_ids(run_dir)
            selected_ids = {page.item_id for page in selected}
            if previous_ids and set(previous_ids) != selected_ids:
                print("Cannot resume legacy predictions with a different selection", file=sys.stderr)
                return 1
            manifest = expected
            for page in selected:
                if (predictions / f"{page.item_id}.md").is_file():
                    manifest["items"][page.item_id]["status"] = "legacy_unverified"
                    legacy_ids.add(page.item_id)
    else:
        # A fresh run replaces predictions and invalidates score/comparison files.
        shutil.rmtree(predictions, ignore_errors=True)
        invalidate_score_artifacts(run_dir)
        manifest = expected

    predictions.mkdir(parents=True, exist_ok=True)
    selected_ids = [page.item_id for page in selected]
    atomic_write_text(
        run_dir / SELECTION_IDS_FILE,
        "".join(f"{item_id}\n" for item_id in selected_ids),
    )
    pages = [
        page for page in selected
        if page.item_id not in legacy_ids
        and manifest["items"][page.item_id].get("status") != "completed"
    ]
    if resume and (
        pages
        or any(item.get("status") != "completed" for item in manifest["items"].values())
    ):
        invalidate_score_artifacts(run_dir)
    if not pages:
        manifest["status"] = "completed" if all(
            item.get("status") == "completed" for item in manifest["items"].values()
        ) else "partial"
        write_run_manifest(run_dir, manifest)
        if legacy_ids:
            print(
                "Nothing to do; legacy predictions were kept as legacy_unverified and "
                "cannot support an accepted comparison"
            )
        else:
            print(f"Nothing to do: every page has verified artifacts in {predictions}")
        return 0 if manifest["status"] == "completed" else 1

    manifest["status"] = "running"
    manifest.pop("finished_at", None)
    write_run_manifest(run_dir, manifest)
    interrupted = False
    for page in pages:
        item = manifest["items"][page.item_id]
        _remove_item_artifacts(predictions, item, page.item_id)
        call_number = item.get("observed_call_count", 0) + 1
        call = {"call_number": call_number, "status": "running", "started_at": utc_now()}
        item.setdefault("observed_calls", []).append(call)
        item["observed_call_count"] = call_number
        item["status"] = "running"
        item["artifacts"] = {}
        write_run_manifest(run_dir, manifest)
        page_start = time.perf_counter()
        toolbox_call_start = time.perf_counter()
        toolbox_call_seconds = None
        input_integrity_check_seconds = 0.0
        try:
            result = toolbox.extract_structure(page.image_path, provider)
            toolbox_call_seconds = time.perf_counter() - toolbox_call_start
            input_check_start = time.perf_counter()
            input_matches_manifest = sha256_file(page.image_path) == item["input_sha256"]
            input_integrity_check_seconds = time.perf_counter() - input_check_start
            if not input_matches_manifest:
                raise RuntimeError("benchmark input changed during extraction")
            canonical = core.payload_to_canonical(result)
            outputs = {
                "markdown": (
                    f"{page.item_id}.md",
                    document_to_markdown(canonical).encode("utf-8"),
                    "text/markdown",
                ),
                "blocks": (
                    f"{page.item_id}.blocks.json",
                    json.dumps(core.provider_blocks(result), ensure_ascii=False,
                               allow_nan=False).encode("utf-8"),
                    "application/json",
                ),
            }
            if save_raw:
                outputs["raw_payload"] = (
                    f"{page.item_id}.provider.json",
                    json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                    "application/json",
                )
            artifacts = {}
            for key, (filename, payload, media_type) in outputs.items():
                atomic_write_bytes(predictions / filename, payload)
                artifacts[key] = {
                    "path": filename,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "media_type": media_type,
                }
            call.update(
                status="completed",
                ended_at=utc_now(),
                toolbox_call_seconds=round(toolbox_call_seconds, 6),
                input_integrity_check_seconds=round(input_integrity_check_seconds, 6),
                page_seconds=round(time.perf_counter() - page_start, 6),
            )
            item["status"] = "completed"
            item["artifacts"] = artifacts
            item["last_error_type"] = None
            print(f"[OK] {page.item_id} ({call['page_seconds']:.1f}s)")
        except KeyboardInterrupt:
            if toolbox_call_seconds is None:
                toolbox_call_seconds = time.perf_counter() - toolbox_call_start
            call.update(
                status="cancelled",
                ended_at=utc_now(),
                toolbox_call_seconds=round(toolbox_call_seconds, 6),
                input_integrity_check_seconds=round(input_integrity_check_seconds, 6),
                page_seconds=round(time.perf_counter() - page_start, 6),
            )
            item["status"] = "cancelled"
            interrupted = True
        except Exception as exc:
            if toolbox_call_seconds is None:
                toolbox_call_seconds = time.perf_counter() - toolbox_call_start
            call.update(
                status="failed",
                ended_at=utc_now(),
                toolbox_call_seconds=round(toolbox_call_seconds, 6),
                input_integrity_check_seconds=round(input_integrity_check_seconds, 6),
                page_seconds=round(time.perf_counter() - page_start, 6),
                error_type=type(exc).__name__,
            )
            item["status"] = "failed"
            item["last_error_type"] = type(exc).__name__
            print(f"[FAIL] {page.item_id} ({type(exc).__name__})", file=sys.stderr)
        finally:
            write_run_manifest(run_dir, manifest)
        if interrupted:
            break

    statuses = [item.get("status") for item in manifest["items"].values()]
    if interrupted:
        manifest["status"] = "cancelled"
    elif all(status == "completed" for status in statuses):
        manifest["status"] = "completed"
    elif not any(status == "completed" for status in statuses) and any(
        status == "failed" for status in statuses
    ):
        manifest["status"] = "failed"
    else:
        manifest["status"] = "partial"
    manifest["finished_at"] = utc_now()
    write_run_manifest(run_dir, manifest)
    completed_total = sum(status == "completed" for status in statuses)
    failed_total = sum(status == "failed" for status in statuses)
    legacy_total = sum(status == "legacy_unverified" for status in statuses)
    print(
        f"Done: {completed_total}/{len(selected)} completed, {failed_total} failed, "
        f"{legacy_total} legacy_unverified, status={manifest['status']} -> {predictions}"
    )
    return 130 if interrupted else (0 if manifest["status"] == "completed" else 1)


def _remove_item_artifacts(predictions: Path, item: dict, item_id: str) -> None:
    names = {
        f"{item_id}.md",
        f"{item_id}.blocks.json",
        f"{item_id}.provider.json",
    }
    for artifact in item.get("artifacts", {}).values():
        name = artifact.get("path") if isinstance(artifact, dict) else None
        if isinstance(name, str) and Path(name).name == name and "/" not in name and "\\" not in name:
            names.add(name)
    for name in names:
        (predictions / name).unlink(missing_ok=True)


def _manifest_ids(run_dir: Path) -> list[str]:
    manifest = run_dir / SELECTION_IDS_FILE
    return manifest.read_text(encoding="utf-8").split() if manifest.exists() else []


def _is_path_segment(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and "/" not in value and "\\" not in value


def _finite(value):
    """Convert non-finite numbers to ``null`` so output is strict JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
