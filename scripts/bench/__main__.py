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
import json
import math
import os
import shutil
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from acessilia_sdk.toolbox.capabilities import provider_default
from acessilia_sdk.toolbox.errors import ToolboxError
from docstruct.export.markdown import document_to_markdown

from backend.services.runtime_lease import file_lease
from scripts.bench import core, toolbox
from scripts.bench.dataset_reference import git_revision
from scripts.bench.datasets import DATASETS
from scripts.bench.input_identity import INPUTS_FILE, check_input, page_identity, run_inputs
from scripts.bench.report import EXTRACTION_FILE, MANIFEST_FILE, compare_runs, invalidate_scores, score_run

VAR = Path(os.environ.get("BENCH_VAR") or Path(__file__).resolve().parents[2] / "var" / "bench")


def _run_lease(run_dir: Path):
    return file_lease(run_dir / ".bench.lock", f"Benchmark run {run_dir} is already in use")


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
    p = dataset_command("run", "run the core on the pages and write predictions")
    p.add_argument("--sample", type=int, help="first N pages only")
    p.add_argument("--item", help="a single item id")
    p.add_argument("--provider", help="Toolbox structure provider override")
    p.add_argument("--save-raw", action="store_true", help="also keep the Toolbox payload")
    p.add_argument("--resume", action="store_true", help="skip pages that already have a prediction")
    dataset_command("score", "score a run against the ground truth")
    dataset_command("submit", "package a run in the benchmark's submission format")
    p = sub.add_parser("compare", help="tune/holdout acceptance of a candidate run")
    p.add_argument("base", type=Path)
    p.add_argument("candidate", type=Path)

    args = parser.parse_args(argv)
    if args.command == "compare":
        try:
            with ExitStack() as leases:
                for run_dir in sorted({args.base.resolve(), args.candidate.resolve()}):
                    if run_dir.is_dir():
                        leases.enter_context(_run_lease(run_dir))
                verdict = compare_runs(args.base, args.candidate)
        except (RuntimeError, ValueError) as error:
            print(json.dumps({
                "accepted": False,
                "status": "incomparable",
                "reason": str(error),
            }, indent=2))
            return 2
        print(json.dumps(_finite(verdict.__dict__), indent=2))
        return 0 if verdict.accepted else 1

    dataset = DATASETS[args.dataset]
    root = args.root or VAR / args.dataset / args.split / "data"
    run_dir = VAR / args.dataset / args.split / args.run
    predictions = run_dir / "predictions"

    if args.command == "download":
        print(f"{dataset.download(args.split, root, args.limit)} pages written to {root}")
        return 0

    with _run_lease(run_dir):
        try:
            pages = dataset.pages(root)
            if not pages:
                if args.command == "score":
                    invalidate_scores(run_dir)
                print(f"No pages under {root}; run `download` first or pass --root", file=sys.stderr)
                return 1
            if args.command == "score":
                manifest = run_dir / MANIFEST_FILE
                if manifest.exists():
                    selected = set(manifest.read_text(encoding="utf-8").split())
                    pages = [p for p in pages if p.item_id in selected]
                report = score_run(pages, predictions, run_dir)
        except (OSError, ValueError) as error:
            if args.command != "score":
                raise
            invalidate_scores(run_dir)
            print(f"Cannot score {run_dir.name}: {error}", file=sys.stderr)
            return 2
        if args.command == "score":
            print(json.dumps(report, indent=2))
            if not report["pages"]:
                print(f"No page of the run has ground truth under {root}", file=sys.stderr)
                return 1
            return 0
        if args.command == "run":
            if args.item:
                pages = [p for p in pages if p.item_id == args.item]
            if args.sample:
                pages = pages[: args.sample]
            return _run(pages, run_dir, args.provider, args.save_raw, resume=args.resume)
        zip_path = dataset.build_submission(pages, predictions, run_dir / "submission")
    print(f"Submission ready: {zip_path}")
    return 0


def _run(selected, run_dir: Path, provider: str | None, save_raw: bool, *, resume: bool = False) -> int:
    predictions = run_dir / "predictions"
    extraction_path = run_dir / EXTRACTION_FILE
    if provider is None:
        provider = toolbox.client_config().providers.get("toolbox_provider") or provider_default(
            "toolbox_provider"
        )
    identities = {page.item_id: page_identity(page) for page in selected}
    if len(identities) != len(selected):
        print("Cannot run duplicate page IDs", file=sys.stderr)
        return 2
    datasets = {(item["dataset"], item["dataset_revision"]) for item in identities.values()}
    if len(datasets) != 1:
        print("Cannot run an empty selection or mixed Dataset revisions", file=sys.stderr)
        return 2
    dataset, revision = next(iter(datasets))
    configuration = {
        "provider": provider,
        "save_raw": save_raw,
        "core_revision": git_revision(Path(__file__).resolve().parents[2]),
        "input_identity_version": 1,
        "dataset": dataset,
        "dataset_revision": revision,
    }
    if resume:
        # Resuming continues a run: earlier predictions stay and the manifest
        # keeps covering every page the run ever intended to score.
        pages = [p for p in selected if not (predictions / f"{p.item_id}.md").exists()]
        try:
            if extraction_path.is_file():
                previous = json.loads(extraction_path.read_text(encoding="utf-8"))
                if previous != configuration:
                    raise ValueError("extraction configuration changed")
            elif any(predictions.glob("*.md")):
                raise ValueError("existing predictions have no recorded extraction configuration")
            recorded = run_inputs(run_dir, required=any(predictions.glob("*.md")))
            for page in selected:
                if page.item_id in recorded or (predictions / f"{page.item_id}.md").exists():
                    check_input(page, recorded)
            identities = {**recorded, **identities}
        except (OSError, ValueError) as error:
            print(f"Cannot resume {run_dir.name}: {error}. Use a new --run name.", file=sys.stderr)
            return 2
        covered = _manifest_ids(run_dir)
        added = [p.item_id for p in selected if p.item_id not in set(covered)]
        if not pages and not added and identities == recorded:
            print(f"Nothing to do: every page of the selection has a prediction in {predictions}")
            return 0
        covered += added
    else:
        # A rerun replaces the previous one: stale predictions would be scored
        # and submitted as if they belonged to this run.
        pages = selected
        covered = [p.item_id for p in selected]
    invalidate_scores(run_dir)
    if not resume and predictions.exists():
        shutil.rmtree(predictions)
    predictions.mkdir(parents=True, exist_ok=True)
    pending_inputs = (run_dir / INPUTS_FILE).with_suffix(".tmp")
    pending_inputs.write_text(json.dumps(identities, indent=2) + "\n", encoding="utf-8")
    pending_inputs.replace(run_dir / INPUTS_FILE)
    if pages or not resume:
        pending_configuration = extraction_path.with_suffix(".tmp")
        pending_configuration.write_text(json.dumps(configuration, indent=2) + "\n", encoding="utf-8")
        pending_configuration.replace(extraction_path)
    manifest_path = run_dir / MANIFEST_FILE
    pending_manifest = manifest_path.with_suffix(".tmp")
    pending_manifest.write_text("".join(f"{i}\n" for i in covered), encoding="utf-8")
    pending_manifest.replace(manifest_path)
    if resume and not pages:
        print(f"Nothing to do: every page of the selection has a prediction in {predictions}")
        return 0
    ok = 0
    for page in pages:
        start = time.perf_counter()
        try:
            result = toolbox.extract_structure(page.image_path, provider)
        except ToolboxError as e:
            print(f"[FAIL] {page.item_id}: {e}", file=sys.stderr)
            continue
        canonical = core.payload_to_canonical(result)
        out = predictions / page.item_id
        provenance = result.get("provenance") or {}
        out.with_suffix(".extraction.json").write_text(json.dumps({
            "provider": result.get("provider") or provenance.get("provider"),
            "provider_version": provenance.get("provider_version"),
            "model_versions": provenance.get("model_versions"),
            "capability_version": provenance.get("capability_version"),
            "input": identities[page.item_id],
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        out.with_suffix(".blocks.json").write_text(
            json.dumps(core.provider_blocks(result), ensure_ascii=False), encoding="utf-8")
        if save_raw:
            out.with_suffix(".provider.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8")
        pending_markdown = out.with_suffix(".md.tmp")
        pending_markdown.write_text(document_to_markdown(canonical), encoding="utf-8")
        pending_markdown.replace(out.with_suffix(".md"))
        ok += 1
        print(f"[OK] {page.item_id} ({time.perf_counter() - start:.1f}s)")
    print(f"Done: {ok}/{len(pages)} pages -> {predictions}")
    return 0 if ok else 1


def _manifest_ids(run_dir: Path) -> list[str]:
    manifest = run_dir / MANIFEST_FILE
    return manifest.read_text(encoding="utf-8").split() if manifest.exists() else []


def _finite(value):
    """``nan`` → ``None``, so the output is strict JSON."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    return value


if __name__ == "__main__":
    raise SystemExit(main())
