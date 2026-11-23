"""The docstruct allowlist only shrinks against the base branch (#764).

``tests/test_architecture_layers.py`` checks the code against
``tests/fixtures/docstruct_import_allowlist.json`` (#758). A pull request that
changes the code and the fixture together still passes that check, so this
script compares the fixture with the base branch's version and fails when the
pull request widens it:

- a module that was not in the base fixture;
- a module reclassified as ``contract``, the only unpinned class;
- a file added to a module's pin, or a name added to a file's pin (a pin
  that had ``*``, a dynamic use, already allowed any name).

Removals and reclassifications between pinned classes are fine. An exception
is an architectural decision (ADR-0028): ``--allow-exceptions`` (the CI passes
it when the pull request has the ``architecture-exception`` label) reports the
widening as a warning instead, and the pull request cites the decision.

Exit codes: 0 when the allowlist does not grow (or the base commit has no
fixture), 1 when it grows, 2 when the baseline cannot be read: an unknown
ref, an unreadable or invalid fixture. The check fails closed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path("tests/fixtures/docstruct_import_allowlist.json")


def widenings(base: dict[str, dict], head: dict[str, dict]) -> list[str]:
    """What ``head`` allows that ``base`` did not, one line per addition."""
    found: list[str] = []
    for module, entry in sorted(head.items()):
        before = base.get(module)
        if before is None:
            found.append(f"new module {module} ({entry['class']})")
            continue
        if entry["class"] == "contract":
            if before["class"] != "contract":
                found.append(f"{module} reclassified {before['class']} -> contract")
            continue
        if before["class"] == "contract":
            continue  # a contract module that becomes pinned only narrows
        pins = before.get("files", {})
        for path, names in sorted(entry.get("files", {}).items()):
            if path not in pins:
                found.append(f"{module}: new importer {path}")
                continue
            if "*" in pins[path]:
                continue  # a dynamic use already allowed any name
            for name in sorted(set(names) - set(pins[path])):
                found.append(f"{module}: {path} adds {name}")
    return found


class BaselineError(RuntimeError):
    """The base fixture could not be read; the check fails closed."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )


def fixture_at(ref: str, repo: Path = REPO_ROOT) -> dict[str, dict] | None:
    """The fixture at ``ref``, or ``None`` when ``ref`` is a commit without it.

    Raises :class:`BaselineError` when ``ref`` does not resolve to a commit,
    or when the fixture exists there and cannot be read or parsed: only a
    valid commit that provably lacks the fixture means "nothing to compare".
    """
    resolved = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if resolved.returncode != 0:
        raise BaselineError(
            f"the base ref {ref!r} does not resolve to a commit; fetch it "
            "(actions/checkout with fetch-depth: 0) or pass a valid --base"
        )
    commit = resolved.stdout.strip()
    tree = _git(repo, "ls-tree", "--name-only", commit, "--", FIXTURE.as_posix())
    if tree.returncode != 0:
        raise BaselineError(f"cannot list {FIXTURE} at {ref}: {tree.stderr.strip()}")
    if not tree.stdout.strip():
        return None
    shown = _git(repo, "show", f"{commit}:{FIXTURE.as_posix()}")
    if shown.returncode != 0:
        raise BaselineError(f"cannot read {FIXTURE} at {ref}: {shown.stderr.strip()}")
    try:
        return json.loads(shown.stdout)
    except json.JSONDecodeError as error:
        raise BaselineError(f"{FIXTURE} at {ref} is not valid JSON: {error}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the base ref, e.g. origin/develop")
    parser.add_argument(
        "--allow-exceptions", action="store_true",
        help="report widenings as warnings (an approved architecture exception)",
    )
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        base = fixture_at(args.base, args.repo)
    except BaselineError as error:
        print(f"::error::docstruct allowlist baseline: {error}")
        return 2
    if base is None:
        print(f"{FIXTURE} does not exist at {args.base}: nothing to compare.")
        return 0
    head_path = args.repo / FIXTURE
    try:
        head = json.loads(head_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"::error::cannot read {head_path}: {error}")
        return 2
    found = widenings(base, head)
    if not found:
        print(f"The docstruct allowlist does not grow against {args.base}.")
        return 0
    level = "warning" if args.allow_exceptions else "error"
    for line in found:
        print(f"::{level}::docstruct allowlist grows: {line}")
    if args.allow_exceptions:
        print(
            "Allowed by the architecture-exception label. The pull request must cite "
            "the decision (docs/architecture/docstruct-import-inventory.md, Exceptions)."
        )
        return 0
    print(
        "The docstruct allowlist only shrinks (ADR-0028, #764): call a Toolbox "
        "capability instead, or record an architectural decision and label the "
        "pull request architecture-exception."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
