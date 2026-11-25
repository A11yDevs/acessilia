"""Record the differential references of an older core (#849).

    uv run python scripts/record_differential_references.py --ref 9d433476 --label core-0.3.11

checks ``--ref`` out in a temporary git worktree, copies this tree's harness
(``tests/differential``: the runner, the fake Toolbox, the cases and the
source PDF) into it, and runs the cases there with that tree's own locked
environment, plus the packages the fake needs at pinned versions
(``runner.PINNED``). The run is hermetic (``runner.hermetic_environment``).

Nothing is published until every case ran and the fake answered every call.
Then ``tests/differential/references/<label>`` gets the cases' normalized
canonical documents and a ``SOURCE.json`` naming the commit, the core version
and the harness identity (``runner.identity``); ``intended.json``, written by
hand, is kept. Recording every case replaces the reference and drops the
cases that no longer exist. Recording some cases keeps the others, and is
refused when the reference was recorded with another commit or harness: the
cases of one reference come from one run of one harness.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.differential.runner import CASES, HARNESS_FILES, PINNED, REFERENCES, identity  # noqa: E402

#: Files of a reference the recording does not write.
KEPT = ("intended.json",)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def _core_version(tree: Path) -> str:
    for line in (tree / "libs" / "core" / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    return "unknown"


def publish(out: Path, target: Path, source: dict[str, Any], cases: list[str], *, complete: bool) -> None:
    """Move the validated outputs of ``out`` to the reference ``target``.

    Every case of ``cases`` must be in ``out`` with no unhandled call, or
    nothing changes. ``complete`` replaces the whole reference (the
    hand-written ``KEPT`` files survive); otherwise only ``cases`` are
    replaced, and only into a reference of the same commit and harness.
    """
    outcomes = {}
    for case in cases:
        path = out / f"{case}.json"
        if not path.is_file():
            raise SystemExit(f"{case}: the run wrote no output")
        outcome = json.loads(path.read_text(encoding="utf-8"))
        if outcome["unhandled"]:
            raise SystemExit(f"{case}: the fake did not answer {outcome['unhandled']}")
        outcomes[case] = path
    if not complete:
        recorded = target / "SOURCE.json"
        if not recorded.is_file() or json.loads(recorded.read_text(encoding="utf-8")) != source:
            raise SystemExit(f"{target.name} was recorded with another commit or harness: record every case")
    staging = target.with_name(f".{target.name}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    if complete or not target.is_dir():
        staging.mkdir(parents=True)
        for name in KEPT:
            if (target / name).is_file():
                shutil.copy(target / name, staging / name)
    else:
        shutil.copytree(target, staging)
    for case, path in outcomes.items():
        shutil.copy(path, staging / f"{case}.json")
    (staging / "SOURCE.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    # The swap: the old reference stays whole until the new one is complete.
    previous = target.with_name(f".{target.name}.previous")
    shutil.rmtree(previous, ignore_errors=True)
    if target.is_dir():
        target.rename(previous)
    staging.rename(target)
    shutil.rmtree(previous, ignore_errors=True)


def record(ref: str, label: str, cases: list[str], *, complete: bool) -> Path:
    commit = _git("rev-parse", ref)
    with tempfile.TemporaryDirectory(prefix="differential-worktree-") as scratch:
        tree = Path(scratch) / "tree"
        _git("worktree", "add", "--detach", str(tree), commit)
        try:
            harness = tree / "tests" / "differential"
            shutil.rmtree(harness, ignore_errors=True)
            harness.mkdir(parents=True)
            for name in (*HARNESS_FILES, "source.pdf"):
                shutil.copy(CASES.parent / name, harness / name)
            shutil.copytree(CASES, harness / "cases")
            out = Path(scratch) / "out"
            pins = [argument for name, version in PINNED.items() for argument in ("--with", f"{name}=={version}")]
            subprocess.run(
                ["uv", "run", "--locked", *pins, "python", "-m", "tests.differential.runner",
                 *(str(harness / "cases" / case / "case.json") for case in cases), "--out", str(out)],
                cwd=tree, check=True,
            )
            source = {"commit": commit, "core_version": _core_version(tree), **identity()}
            target = REFERENCES / label
            publish(out, target, source, cases, complete=complete)
        finally:
            # A failure here must not hide the one that brought us here.
            try:
                _git("worktree", "remove", "--force", str(tree))
            except subprocess.CalledProcessError as error:
                print(f"warning: could not remove the worktree {tree}: {error.stderr}", file=sys.stderr)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", required=True, help="the commit to record (before a migration)")
    parser.add_argument("--label", required=True, help="the reference's directory name, e.g. core-0.3.11")
    parser.add_argument("cases", nargs="*", help="case names (default: every case, replacing the reference)")
    arguments = parser.parse_args()
    every = sorted(path.parent.name for path in CASES.glob("*/case.json"))
    unknown = sorted(set(arguments.cases) - set(every))
    if unknown:
        raise SystemExit(f"unknown cases: {unknown}")
    cases = arguments.cases or every
    print(record(arguments.ref, arguments.label, cases, complete=not arguments.cases))


if __name__ == "__main__":
    main()
