"""Replay and evaluate a frozen baseline/candidate pair in isolated directories."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.drbench.experiments.eval.frozen_inputs import freeze, sha256, write_json
from scripts.drbench.experiments.eval.replay_report import check_inventory, make_report


def verify_inputs(root: Path, manifest: dict) -> None:
    for name, digest in manifest["input_hashes"].items():
        if sha256(root / name) != digest:
            raise ValueError(f"Frozen input changed: {name}")
    if sha256(root / "pages.json") != manifest["selection_sha256"]:
        raise ValueError("Frozen selection changed")


def verify_sources(root: Path) -> dict:
    # Git exports have no .git metadata. Hash every exported file used by this run.
    return {str(p.relative_to(root)): sha256(p) for p in sorted((root / "sources").rglob("*")) if p.is_file()}


def check_sources(root: Path, original: dict) -> dict:
    current = verify_sources(root)
    if any(current.get(name) != digest for name, digest in original.items()):
        raise ValueError("Frozen source changed during evaluation")
    generated = {name: digest for name, digest in current.items() if name not in original}
    # Importing the backend compiles its versioned .po catalogues into ignored .mo files.
    if any(Path(name).suffix != ".mo" or str(Path(name).with_suffix(".po")) not in original
           for name in generated):
        raise ValueError("Unexpected file created inside frozen source")
    return generated


def execute(command: list[str], cwd: Path, env: dict, log: Path, manifest: dict, root: Path) -> None:
    entry = {"command": command, "cwd": str(cwd), "log": str(log.relative_to(root))}
    manifest["commands"].append(entry)
    write_json(root / "manifest.json", manifest)
    start = time.monotonic()
    with log.open("w") as stream:
        completed = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
    entry.update(returncode=completed.returncode, seconds=time.monotonic() - start)
    write_json(root / "manifest.json", manifest)
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}); see {log}")


def evaluate(root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["status"] != "frozen":
        raise ValueError("Only a fresh frozen run can be evaluated; use a new output directory")
    pages = json.loads((root / "pages.json").read_text())
    logs = root / "logs"
    logs.mkdir()
    manifest.update(status="running", commands=[],
                    runtime={"python": sys.version, "executable": sys.executable,
                             "platform": platform.platform(),
                             "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}})
    runner_dir = Path(__file__).parent
    manifest["runner_hashes"] = {p.name: sha256(p) for p in (
        Path(__file__), runner_dir / "replay_worker.py", runner_dir / "replay_report.py",
        runner_dir / "frozen_inputs.py",
    )}
    try:
        verify_inputs(root, manifest)
        if sha256(root / "source-hashes.json") != manifest["source_hashes_sha256"]:
            raise ValueError("Frozen source hash inventory changed")
        source_hashes = json.loads((root / "source-hashes.json").read_text())
        if verify_sources(root) != source_hashes:
            raise ValueError("Frozen source changed before evaluation")
        for variant in ("baseline", "candidate"):
            source = root / "sources" / variant
            acc, toolbox = source / "acessilia", source / "toolbox"
            settings = manifest["variants"][variant]
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPATH"] = os.pathsep.join(map(str, (toolbox / "src", acc / "libs/docstruct/src", acc)))
            out = root / variant
            out.mkdir()
            execute([sys.executable, str(runner_dir / "replay_worker.py"), "--run", str(root),
                     "--variant", variant], acc, env, logs / f"{variant}-replay.log", manifest, root)
            for provider in ("docling", "mineru"):
                check_inventory(out / provider, pages)
                for page in pages:
                    json.loads((out / provider / f"{page['id']}.blocks.json").read_text())
            # Do not allow arbitrary flags to redirect input/output or override recorded policy.
            flags = settings["fusion_args"]
            forbidden = ("--out", "--docling", "--mineru", "--policy")
            if any(flag.split("=", 1)[0] in forbidden for flag in flags):
                raise ValueError("fusion_args cannot override paths or policy")
            execute([sys.executable, str(runner_dir / "replay_worker.py"), "--run", str(root),
                     "--variant", variant, "--fuse"], acc, env,
                    logs / f"{variant}-fusion.log", manifest, root)
            settings.update(json.loads((out / "fusion-config.json").read_text()))
            check_inventory(out / "fusion", pages)
            (out / "result").mkdir()
            for batch in sorted({p["batch"] for p in pages}):
                predictions = out / f"batch-{batch:02d}"
                for page in [p for p in pages if p["batch"] == batch]:
                    target = predictions / page["subject"] / f"{page['document_id']}_page_{page['page']}-{page['page']}.md"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(out / "fusion" / f"{page['id']}.drbench.md", target)
                config = {"end2end_eval": {
                    "metrics": {"text_block": {"metric": ["Edit_dist"]},
                                "reading_order": {"metric": ["Edit_dist"]},
                                "table": {"metric": ["TEDS", "Edit_dist"]},
                                "display_formula": {"metric": ["Edit_dist"]}},
                    "dataset": {"dataset_name": "multipage_md2md_dataset",
                                "ground_truth": {"data_path": str(root / "data/hf/dev")},
                                "prediction": {"data_path": str(predictions)}, "match_method": "quick_match"},
                }}
                cfg = out / f"batch-{batch:02d}.json"
                write_json(cfg, config)  # JSON is also accepted by the evaluator's YAML loader.
                execute([sys.executable, str(root / "sources/evaluator/tools/multipage_pdf_validation.py"),
                         "--config", str(cfg), "--save_name", f"batch-{batch:02d}"],
                        out, env, logs / f"{variant}-batch-{batch:02d}.log", manifest, root)
                print(f"Evaluated {variant} batch {batch}", flush=True)
        verify_inputs(root, manifest)
        manifest["generated_catalogue_hashes"] = check_sources(root, source_hashes)
        if any(sha256(runner_dir / name) != digest for name, digest in manifest["runner_hashes"].items()):
            raise ValueError("Runner changed during evaluation")
        summary = make_report(root)
        manifest.update(status="completed", quality_gate=summary["quality_gate"])
        return summary
    except Exception as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        write_json(root / "manifest.json", manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--require-zero-regressions", action="store_true")
    args = parser.parse_args()
    if args.frozen:
        if args.spec or args.out or args.limit:
            parser.error("--frozen cannot be combined with --spec/--out/--limit")
        root = args.frozen
    else:
        if not args.spec or not args.out:
            parser.error("Provide --spec and --out, or --frozen")
        freeze(args.spec, args.out, args.limit)
        root = args.out
    summary = evaluate(root)
    print(json.dumps(summary, indent=2, allow_nan=False))
    return int(args.require_zero_regressions and summary["quality_gate"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
