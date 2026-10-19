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
import os
import sys
import time
from pathlib import Path

from docstruct.export.markdown import document_to_markdown

from backend.tools.toolbox_client import ToolboxError
from scripts.bench import core, toolbox
from scripts.bench.datasets import DATASETS
from scripts.bench.report import compare_runs, score_run

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
        verdict = compare_runs(args.base, args.candidate)
        print(json.dumps(verdict.__dict__, indent=2))
        return 0 if verdict.accepted else 1

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
        if args.resume:
            pages = [p for p in pages if not (predictions / f"{p.item_id}.md").exists()]
        if args.sample:
            pages = pages[: args.sample]
        return _run(pages, predictions, args.provider, args.save_raw)
    if args.command == "score":
        print(json.dumps(score_run(pages, predictions, run_dir), indent=2))
        return 0
    zip_path = dataset.build_submission(pages, predictions, run_dir / "submission")
    print(f"Submission ready: {zip_path}")
    return 0


def _run(pages, predictions: Path, provider: str | None, save_raw: bool) -> int:
    predictions.mkdir(parents=True, exist_ok=True)
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
        out.with_suffix(".md").write_text(document_to_markdown(canonical), encoding="utf-8")
        out.with_suffix(".blocks.json").write_text(
            json.dumps(core.provider_blocks(result), ensure_ascii=False), encoding="utf-8")
        if save_raw:
            out.with_suffix(".provider.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8")
        ok += 1
        print(f"[OK] {page.item_id} ({time.perf_counter() - start:.1f}s)")
    print(f"Done: {ok}/{len(pages)} pages -> {predictions}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
