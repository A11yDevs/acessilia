"""No function grows past the complexity (<= 15) or line-length (<= 100) limits (#612, #652).

The limits and the legacy functions outside ``libs/core/src`` that were above
them when this test landed live in
``tests/fixtures/function_complexity_allowlist.json``.

- Every function in ``libs/core/src/acessilia_core`` must stay at or below both
  limits with no allowlist entry (``test_the_core_has_no_allowlisted_functions``).
- Outside ``libs/core/src``, an unlisted function must stay at or below both
  limits.
- A listed function records only the dimension(s) above the limit (``lines > 100``
  and/or ``complexity > 15``). Neither dimension may grow above its recorded
  ceiling (or the global limit when a dimension is not listed).
- When a listed dimension shrinks, its recorded ceiling must be lowered, and
  once a dimension reaches the global limit it must be removed from the entry
  (removing the function entry itself once neither dimension exceeds its limit),
  so the allowlist only shrinks.
"""

from __future__ import annotations

import ast
import json
import warnings
from pathlib import Path

import pytest

from scripts.architecture_metrics import Function, iter_functions

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "tests" / "fixtures" / "function_complexity_allowlist.json"

SCANNED_ROOTS = (
    "libs/core/src/acessilia_core",
    "backend",
    "frontend",
    "libs/sdk/src/acessilia_sdk",
    "libs/docstruct/src/docstruct",
)
CORE_PREFIX = "libs/core/src/"


def _allowlist() -> tuple[int, int, dict[str, dict[str, int]]]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return data["max_lines"], data["max_complexity"], data["functions"]


def _parse(path: Path) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def repository_functions() -> dict[str, Function]:
    found: dict[str, Function] = {}
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            for fn in iter_functions(_parse(path), rel):
                key = f"{rel}::{fn.qualname}"
                assert key not in found, f"Duplicate function key: {key}"
                found[key] = fn
    return found


def _check_growth(
    functions: dict[str, Function],
    allowed: dict[str, dict[str, int]],
    *,
    max_lines: int,
    max_complexity: int,
) -> list[str]:
    failures: list[str] = []
    for key, fn in sorted(functions.items()):
        entry = allowed.get(key, {})
        line_limit = entry.get("lines", max_lines)
        cc_limit = entry.get("complexity", max_complexity)
        if fn.lines > line_limit:
            note = f"{line_limit} allowed" if "lines" in entry else f"the limit is {max_lines}"
            failures.append(f"  {key}: {fn.lines} lines ({note})")
        if fn.complexity > cc_limit:
            note = (
                f"{cc_limit} allowed"
                if "complexity" in entry
                else f"the limit is {max_complexity}"
            )
            failures.append(f"  {key}: complexity {fn.complexity} ({note})")
    return failures


def _check_stale(
    functions: dict[str, Function],
    allowed: dict[str, dict[str, int]],
    *,
    max_lines: int,
    max_complexity: int,
) -> list[str]:
    stale: list[str] = []
    for key, entry in sorted(allowed.items()):
        fn = functions.get(key)
        if fn is None:
            stale.append(f"  {key}: no longer exists; remove the entry")
            continue
        if not entry:
            stale.append(f"  {key}: empty allowlist entry; remove the entry")
            continue
        unknown = sorted(set(entry) - {"lines", "complexity"})
        if unknown:
            stale.append(f"  {key}: unknown dimension(s) {unknown}")
        if "lines" in entry:
            recorded = entry["lines"]
            if recorded <= max_lines:
                stale.append(
                    f"  {key} [lines]: allowlist ceiling {recorded} is at or below {max_lines}; remove 'lines'"
                )
            elif fn.lines <= max_lines:
                stale.append(
                    f"  {key} [lines]: {fn.lines} lines, at or below {max_lines}; remove 'lines'"
                )
            elif fn.lines < recorded:
                stale.append(f"  {key} [lines]: {recorded} -> {fn.lines}")
        if "complexity" in entry:
            recorded = entry["complexity"]
            if recorded <= max_complexity:
                stale.append(
                    f"  {key} [complexity]: allowlist ceiling {recorded} is at or below {max_complexity}; remove 'complexity'"
                )
            elif fn.complexity <= max_complexity:
                stale.append(
                    f"  {key} [complexity]: complexity {fn.complexity}, at or below {max_complexity}; remove 'complexity'"
                )
            elif fn.complexity < recorded:
                stale.append(f"  {key} [complexity]: {recorded} -> {fn.complexity}")
    return stale


def test_the_scanned_roots_exist() -> None:
    missing = [root for root in SCANNED_ROOTS if not (REPO_ROOT / root).is_dir()]

    assert not missing, f"Scanned roots that no longer exist: {missing}"


def test_the_core_has_no_allowlisted_functions() -> None:
    """#612 reduced libs/core/src to 0 functions over 100 lines or CC 15; it stays at 0."""
    _, _, allowed = _allowlist()
    core_entries = sorted(key for key in allowed if key.startswith(CORE_PREFIX))

    assert not core_entries, (
        "Functions under libs/core/src must not be added to the complexity/size allowlist:\n  "
        + "\n  ".join(core_entries)
    )


def test_no_function_grows_past_the_limits(
    repository_functions: dict[str, Function],
) -> None:
    max_lines, max_complexity, allowed = _allowlist()
    failures = _check_growth(
        repository_functions,
        allowed,
        max_lines=max_lines,
        max_complexity=max_complexity,
    )

    assert not failures, (
        "Functions above their complexity or line limit; decompose them instead of raising a ceiling:\n"
        + "\n".join(failures)
    )


def test_the_allowlist_only_shrinks(
    repository_functions: dict[str, Function],
) -> None:
    max_lines, max_complexity, allowed = _allowlist()
    stale = _check_stale(
        repository_functions,
        allowed,
        max_lines=max_lines,
        max_complexity=max_complexity,
    )

    assert not stale, (
        f"Update {ALLOWLIST_PATH.relative_to(REPO_ROOT)}:\n" + "\n".join(stale)
    )


def test_the_listed_functions_are_in_scanned_roots() -> None:
    _, _, allowed = _allowlist()
    prefixes = tuple(f"{root}/" for root in SCANNED_ROOTS)
    outside = [
        key for key in sorted(allowed) if not key.split("::", 1)[0].startswith(prefixes)
    ]

    assert not outside, f"Listed functions outside the scanned roots: {outside}"


def test_per_dimension_ratchet_checks_lines_and_complexity_independently() -> None:
    fn_ok = Function("backend/a.py", "f", lines=80, complexity=17, qualname="f")
    fn_grew_lines_within_limit = Function(
        "backend/a.py", "f", lines=95, complexity=17, qualname="f"
    )
    fn_grew_lines_over_limit = Function(
        "backend/a.py", "f", lines=101, complexity=17, qualname="f"
    )
    fn_grew_cc = Function(
        "backend/a.py", "f", lines=80, complexity=18, qualname="f"
    )
    fn_shrank_cc_still_over = Function(
        "backend/a.py", "f", lines=80, complexity=16, qualname="f"
    )
    fn_shrank_cc_to_limit = Function(
        "backend/a.py", "f", lines=80, complexity=15, qualname="f"
    )
    allowed = {"backend/a.py::f": {"complexity": 17}}

    assert (
        _check_growth(
            {"backend/a.py::f": fn_ok}, allowed, max_lines=100, max_complexity=15
        )
        == []
    )
    assert (
        _check_growth(
            {"backend/a.py::f": fn_grew_lines_within_limit},
            allowed,
            max_lines=100,
            max_complexity=15,
        )
        == []
    )
    assert _check_growth(
        {"backend/a.py::f": fn_grew_lines_over_limit},
        allowed,
        max_lines=100,
        max_complexity=15,
    ) == ["  backend/a.py::f: 101 lines (the limit is 100)"]
    assert _check_growth(
        {"backend/a.py::f": fn_grew_cc},
        allowed,
        max_lines=100,
        max_complexity=15,
    ) == ["  backend/a.py::f: complexity 18 (17 allowed)"]

    assert (
        _check_stale(
            {"backend/a.py::f": fn_ok}, allowed, max_lines=100, max_complexity=15
        )
        == []
    )
    assert _check_stale(
        {"backend/a.py::f": fn_shrank_cc_still_over},
        allowed,
        max_lines=100,
        max_complexity=15,
    ) == ["  backend/a.py::f [complexity]: 17 -> 16"]
    assert _check_stale(
        {"backend/a.py::f": fn_shrank_cc_to_limit},
        allowed,
        max_lines=100,
        max_complexity=15,
    ) == [
        "  backend/a.py::f [complexity]: complexity 15, at or below 15; remove 'complexity'"
    ]
