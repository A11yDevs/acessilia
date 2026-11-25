"""Record the differential references of an older core (#849).

    uv run python scripts/record_differential_references.py --ref 9d433476 --label core-0.3.11

checks ``--ref`` out in a temporary git worktree, copies this tree's harness
(``tests/differential``: the fake Toolbox, the runner, the cases and the
source PDF) into it, and runs every case there with that tree's own
environment (``uv run --locked``, plus Pillow, which the fake needs and an
older lock may lack). Each case's normalized canonical document lands in
``tests/differential/references/<label>/<case>.json``, next to a
``SOURCE.json`` that names the commit and the core version.

Record again when a case changes, or to add a reference; the intended
differences of a reference (``intended.json``) are written by hand.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "differential"
COPIED = ("__init__.py", "fake_toolbox.py", "runner.py", "source.pdf", "cases")


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _core_version(tree: Path) -> str:
    for line in (tree / "libs" / "core" / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    return "unknown"


def record(ref: str, label: str, cases: list[str]) -> Path:
    commit = _git("rev-parse", ref)
    target = HARNESS / "references" / label
    with tempfile.TemporaryDirectory(prefix="differential-worktree-") as scratch:
        tree = Path(scratch) / "tree"
        _git("worktree", "add", "--detach", str(tree), commit)
        try:
            harness = tree / "tests" / "differential"
            shutil.rmtree(harness, ignore_errors=True)
            harness.mkdir(parents=True)
            for name in COPIED:
                source = HARNESS / name
                if source.is_dir():
                    shutil.copytree(source, harness / name)
                else:
                    shutil.copy(source, harness / name)
            out = Path(scratch) / "out"
            case_files = [str(harness / "cases" / name / "case.json") for name in cases]
            subprocess.run(
                ["uv", "run", "--locked", "--with", "pillow>=11", "python", "-m",
                 "tests.differential.runner", *case_files, "--out", str(out)],
                cwd=tree, check=True,
            )
            target.mkdir(parents=True, exist_ok=True)
            for result in sorted(out.glob("*.json")):
                outcome = json.loads(result.read_text(encoding="utf-8"))
                if outcome["unhandled"]:
                    raise SystemExit(f"{result.stem}: the fake did not answer {outcome['unhandled']}")
                shutil.copy(result, target / result.name)
            (target / "SOURCE.json").write_text(json.dumps({
                "commit": commit, "core_version": _core_version(tree),
            }, indent=2) + "\n", encoding="utf-8")
        finally:
            _git("worktree", "remove", "--force", str(tree))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", required=True, help="the commit to record (before a migration)")
    parser.add_argument("--label", required=True, help="the references' directory name, e.g. core-0.3.11")
    parser.add_argument("cases", nargs="*", help="case names (default: every case)")
    arguments = parser.parse_args()
    cases = arguments.cases or sorted(path.parent.name for path in (HARNESS / "cases").glob("*/case.json"))
    print(record(arguments.ref, arguments.label, cases))


if __name__ == "__main__":
    sys.exit(main())
