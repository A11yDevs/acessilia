"""No module of the core grows past the size limit (decision D4, #402, #365).

The limit and the modules that were above it when this test landed live in
``tests/fixtures/module_size_allowlist.json``. A module outside the list must
stay at the limit or below. A listed module may not grow; when it shrinks, its
count is lowered, and its entry is removed once it is at the limit or below, so
the list only shrinks. ``docs/architecture/pddl-orchestrator-inventory.md``
records the decision. The scan covers every module ADR-0016 places in the
core, wherever it is today; ``libs/core`` joins it when the core moves there.

A module's size is its number of lines (``str.splitlines``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "tests" / "fixtures" / "module_size_allowlist.json"

#: The folders and files that hold the core's modules today (ADR-0016). The
#: service's few modules inside them are scanned too; they are far below the
#: limit.
SCANNED_ROOTS = (
    "backend/agents",
    "backend/ai",
    "backend/core",
    "backend/tools",
)
#: Single files outside the roots above. The message modules were here until
#: ADR-0016's step 2 gathered them into backend/core/i18n, which backend/core covers.
SCANNED_FILES: tuple[str, ...] = ()


def _allowlist() -> tuple[int, dict[str, int]]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return data["limit"], data["files"]


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


@pytest.fixture(scope="module")
def module_sizes() -> dict[str, int]:
    sizes = {}
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            sizes[path.relative_to(REPO_ROOT).as_posix()] = _lines(path)
    for name in SCANNED_FILES:
        # A missing file is reported by test_the_scanned_roots_exist.
        if (REPO_ROOT / name).is_file():
            sizes[name] = _lines(REPO_ROOT / name)
    return sizes


def test_the_scanned_roots_exist() -> None:
    missing = [root for root in SCANNED_ROOTS if not (REPO_ROOT / root).is_dir()]
    missing += [name for name in SCANNED_FILES if not (REPO_ROOT / name).is_file()]

    assert not missing, (
        f"Scanned paths that no longer exist: {missing}; update SCANNED_ROOTS or SCANNED_FILES"
    )


def test_no_module_grows_past_the_limit(module_sizes: dict[str, int]) -> None:
    """A module above the limit must be listed, and no larger than its count."""
    limit, allowed = _allowlist()
    failures = [
        f"  {path}: {size} lines, "
        + (f"{allowed[path]} allowed" if path in allowed else f"the limit is {limit}")
        for path, size in sorted(module_sizes.items())
        if size > allowed.get(path, limit)
    ]

    assert not failures, (
        "Modules above their size; split them (decision D4) instead of raising a count:\n"
        + "\n".join(failures)
    )


def test_the_allowlist_only_shrinks(module_sizes: dict[str, int]) -> None:
    """Each count is the module's current size, and only modules above the limit are listed."""
    limit, allowed = _allowlist()
    stale = []
    for path, count in sorted(allowed.items()):
        size = module_sizes.get(path)
        if size is None:
            stale.append(f"  {path}: no longer exists; remove the entry")
        elif size <= limit:
            stale.append(f"  {path}: {size} lines, at or below {limit}; remove the entry")
        elif size < count:
            stale.append(f"  {path}: {count} -> {size}")

    assert not stale, f"Update {ALLOWLIST_PATH.relative_to(REPO_ROOT)}:\n" + "\n".join(stale)


def test_the_listed_modules_are_scanned() -> None:
    _, allowed = _allowlist()
    outside = [
        path for path in allowed
        if path not in SCANNED_FILES and not path.startswith(tuple(f"{root}/" for root in SCANNED_ROOTS))
    ]

    assert not outside, f"Listed modules outside the scanned roots: {outside}"
