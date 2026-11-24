"""Fail when structural duplication grows beyond the accepted #656 remainder."""

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
TOTAL_KEYS = ("groups", "functions_in_groups", "lines_in_groups")


def group_signature(group: dict[str, Any]) -> frozenset[str]:
    """A stable identity for one duplicate group, independent of its order."""
    return frozenset(
        f"{function['path']}:{function['qualname']}"
        for function in group["functions"]
    )


def violations(allowed: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """The ways ``current`` duplication exceeds ``allowed``."""
    allowed_groups = {frozenset(group) for group in allowed["groups"]}
    current_groups = {group_signature(group) for group in current["groups"]}
    found = [
        "new duplicate group: " + ", ".join(sorted(group))
        for group in sorted(current_groups - allowed_groups, key=sorted)
    ]
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

    allowed = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    current = quality.collect(args.rev)["duplication"]
    found = violations(allowed, current)
    if found:
        for line in found:
            print(f"::error::duplication ratchet: {line}")
        print(
            "Update tests/fixtures/duplication-allowlist.json only for a reviewed, "
            "justified remainder; otherwise consolidate the new duplicate."
        )
        return 1
    print(
        "Duplication ratchet passed: "
        f"{current['totals']['groups']} groups, "
        f"{current['totals']['functions_in_groups']} functions, "
        f"{current['totals']['lines_in_groups']} lines."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
