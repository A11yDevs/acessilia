"""Fail when structural duplication grows beyond the accepted #656 remainder.

The ratchet compares duplicate group identity, not physical line counts: a
comment, blank line or docstring must not look like new duplication. The
diagnostic tool still reports line counts; the guard enforces groups and
functions only. An allowed group that disappears must be removed from the
allowlist in the same pull request, so a later reintroduction is refused.

The underlying detector is diagnostic and skips unparseable files. A strict
parse mode is a follow-up; until then the guard cannot prove that every file
was analysed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import architecture_quality as quality  # noqa: E402

ALLOWLIST = ROOT / "tests" / "fixtures" / "duplication-allowlist.json"
TOTAL_KEYS = ("groups", "functions_in_groups")


def group_signature(group: dict[str, Any]) -> frozenset[str]:
    """A stable identity for one duplicate group, independent of its order."""
    return frozenset(
        f"{function['path']}:{function['qualname']}"
        for function in group["functions"]
    )


def load_allowlist(path: Path | None = None) -> dict[str, Any]:
    """Read and validate the allowlist, reporting the exact invalid field."""
    path = ALLOWLIST if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: cannot read the allowlist: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the allowlist must be a JSON object")

    groups = data.get("groups")
    if not isinstance(groups, list):
        raise ValueError(f"{path}: groups must be a list")
    signatures: list[frozenset[str]] = []
    for index, group in enumerate(groups):
        if (
            not isinstance(group, list)
            or len(group) < 2
            or any(not isinstance(item, str) or not item for item in group)
        ):
            raise ValueError(
                f"{path}: groups[{index}] must be a list of at least two "
                "non-empty path:qualname strings"
            )
        signatures.append(frozenset(group))
    if len(set(signatures)) != len(signatures):
        raise ValueError(f"{path}: groups contains duplicate entries")

    totals = data.get("totals")
    if not isinstance(totals, dict):
        raise ValueError(f"{path}: totals must be an object")
    for key in TOTAL_KEYS:
        value = totals.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{path}: totals.{key} must be a non-negative integer")
    if totals["groups"] != len(groups):
        raise ValueError(
            f"{path}: totals.groups must equal the number of groups "
            f"({len(groups)})"
        )
    functions = sum(len(group) for group in groups)
    if totals["functions_in_groups"] != functions:
        raise ValueError(
            f"{path}: totals.functions_in_groups must equal the sum of group "
            f"sizes ({functions})"
        )
    return data


def violations(allowed: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """The ways ``current`` duplication differs from ``allowed``."""
    allowed_groups = {frozenset(group) for group in allowed["groups"]}
    current_groups = {group_signature(group) for group in current["groups"]}
    found = [
        "new duplicate group: " + ", ".join(sorted(group))
        for group in sorted(current_groups - allowed_groups, key=sorted)
    ]
    found.extend(
        "stale allowlist group: " + ", ".join(sorted(group))
        for group in sorted(allowed_groups - current_groups, key=sorted)
    )
    for key in TOTAL_KEYS:
        if current["totals"][key] > allowed["totals"][key]:
            found.append(
                f"{key} grew: {current['totals'][key]} > {allowed['totals'][key]}"
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", default="HEAD", help="git revision to measure")
    args = parser.parse_args(argv)

    try:
        allowed = load_allowlist()
    except ValueError as error:
        print(f"::error::duplication ratchet: {error}")
        return 2

    current = quality.collect(args.rev)["duplication"]
    found = violations(allowed, current)
    if found:
        for line in found:
            print(f"::error::duplication ratchet: {line}")
        print(
            "Remove stale exceptions and their totals in the same change that "
            "fixes them; add a new exception only for a reviewed, justified "
            "remainder."
        )
        return 1
    print(
        "Duplication ratchet passed: "
        f"{current['totals']['groups']} groups, "
        f"{current['totals']['functions_in_groups']} functions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
