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


def _fixture_at(ref: str) -> dict[str, dict] | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{FIXTURE.as_posix()}"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    return json.loads(result.stdout) if result.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the base ref, e.g. origin/develop")
    parser.add_argument(
        "--allow-exceptions", action="store_true",
        help="report widenings as warnings (an approved architecture exception)",
    )
    args = parser.parse_args(argv)

    base = _fixture_at(args.base)
    if base is None:
        print(f"{FIXTURE} does not exist at {args.base}: nothing to compare.")
        return 0
    head = json.loads((REPO_ROOT / FIXTURE).read_text(encoding="utf-8"))
    found = widenings(base, head)
    if not found:
        print(f"The docstruct allowlist does not grow against {args.base}.")
        return 0
    level = "warning" if args.allow_exceptions else "error"
    for line in found:
        print(f"::{level}::docstruct allowlist grows: {line}")
    if args.allow_exceptions:
        print("Allowed by the architecture-exception label; cite the decision in the pull request.")
        return 0
    print(
        "The docstruct allowlist only shrinks (ADR-0028, #764): call a Toolbox "
        "capability instead, or record an architectural decision and label the "
        "pull request architecture-exception."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
