"""No function grows past the complexity (<= 15) or line-length (<= 100) limits (#612, #652).

The limits and the legacy functions outside ``libs/core/src`` that were above
them when this test landed live in
``tests/fixtures/function_complexity_allowlist.json``.

- Every function in ``libs/core/src/acessilia_core`` must stay at or below both
  limits with no allowlist entry (``test_the_core_has_no_allowlisted_functions``).
- Outside ``libs/core/src``, an unlisted function must stay at or below both
  limits, and no new function key may be added to the allowlist
  (``INITIAL_LEGACY_CEILINGS`` freezes the initial set and upper bounds).
- A listed function records only the dimension(s) above the limit (``lines > 100``
  and/or ``complexity > 15``). Neither dimension may grow above its recorded
  ceiling (or the global limit when a dimension is not listed).
- When a listed dimension shrinks, its recorded ceiling in
  ``tests/fixtures/function_complexity_allowlist.json`` must be lowered, and
  once a dimension reaches the global limit it must be removed from the entry
  (removing the function entry itself once neither dimension exceeds its limit),
  so the allowlist only shrinks.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import warnings
from pathlib import Path

import pytest

from scripts.architecture_metrics import Function, iter_functions

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "tests" / "fixtures" / "function_complexity_allowlist.json"
CORE_GUARD_PATH = REPO_ROOT / "libs" / "core" / "tests" / "test_function_complexity.py"

MAX_LINES = 100
MAX_COMPLEXITY = 15

SCANNED_ROOTS = (
    "libs/core/src/acessilia_core",
    "backend",
    "frontend",
    "libs/sdk/src/acessilia_sdk",
    "libs/docstruct/src/docstruct",
)
CORE_PREFIX = "libs/core/src/"

#: Minimum expected function count per root so a broken traversal cannot pass silently.
MIN_FUNCTIONS_PER_ROOT: dict[str, int] = {
    "libs/core/src/acessilia_core": 700,
    "backend": 200,
    "frontend": 70,
    "libs/sdk/src/acessilia_sdk": 180,
    "libs/docstruct/src/docstruct": 550,
}

#: Frozen landing snapshot (#652): the allowlist JSON may only hold a subset of
#: these 49 keys, and each dimension's ceiling in the JSON may only be at or
#: below its initial value here. When a legacy function shrinks or drops within
#: limits, only ``tests/fixtures/function_complexity_allowlist.json`` needs to be
#: updated.
INITIAL_LEGACY_CEILINGS: dict[str, dict[str, int]] = {
    "backend/api/routes/jobs.py::submit_job": {"complexity": 17},
    "backend/api/worker.py::JobExecutor.run": {"lines": 325, "complexity": 43},
    "backend/api/worker.py::recover_pending_jobs": {"lines": 104, "complexity": 19},
    "backend/service.py::process": {"lines": 238, "complexity": 43},
    "backend/services/model_calls.py::ModelCallExecutor._invoke": {"complexity": 20},
    "frontend/telegram/handlers/document.py::_poll_job": {"lines": 104, "complexity": 19},
    "libs/docstruct/src/docstruct/adapters/mineru.py::extract_mineru_blocks": {"complexity": 16},
    "libs/docstruct/src/docstruct/adapters/mineru.py::format_mineru_block_text": {"complexity": 43},
    "libs/docstruct/src/docstruct/blocks/lists.py::recover_empty_lettered_list_items": {
        "lines": 131,
        "complexity": 53,
    },
    "libs/docstruct/src/docstruct/canonical.py::_enrich_math_blocks": {"complexity": 20},
    "libs/docstruct/src/docstruct/canonical.py::_sanitize_structured_blocks": {"complexity": 23},
    "libs/docstruct/src/docstruct/canonical.py::_sanitize_table_ast": {"complexity": 21},
    "libs/docstruct/src/docstruct/export/html.py::_render_html_table_row": {"complexity": 21},
    "libs/docstruct/src/docstruct/export/html.py::_safe_mathml": {"complexity": 16},
    "libs/docstruct/src/docstruct/export/page_text.py::blocks_text": {"complexity": 16},
    "libs/docstruct/src/docstruct/export/pandoc_ast.py::_prose_inlines": {"complexity": 16},
    "libs/docstruct/src/docstruct/fusion/_hungarian.py::linear_sum_assignment": {"complexity": 21},
    "libs/docstruct/src/docstruct/fusion/adjudication.py::decide": {"complexity": 16},
    "libs/docstruct/src/docstruct/fusion/differ.py::_pick": {"complexity": 17},
    "libs/docstruct/src/docstruct/fusion/differ.py::merge_blocks": {
        "lines": 198,
        "complexity": 89,
    },
    "libs/docstruct/src/docstruct/fusion/noise.py::fuse_line_runs": {"complexity": 25},
    "libs/docstruct/src/docstruct/fusion/noise.py::group_split_blocks": {"complexity": 30},
    "libs/docstruct/src/docstruct/fusion/noise.py::split_decor": {"complexity": 17},
    "libs/docstruct/src/docstruct/fusion/noise.py::suppress_in_regions": {"complexity": 38},
    "libs/docstruct/src/docstruct/fusion/page_select.py::fuse": {"complexity": 19},
    "libs/docstruct/src/docstruct/fusion/xycut.py::_order": {"complexity": 17},
    "libs/docstruct/src/docstruct/fusion/xycut.py::reorder": {"complexity": 21},
    "libs/docstruct/src/docstruct/geometry/reading_order.py::_column_bounds": {"complexity": 18},
    "libs/docstruct/src/docstruct/geometry/reading_order.py::_extract_bbox": {"complexity": 17},
    "libs/docstruct/src/docstruct/geometry/reading_order.py::_order_body_columns": {
        "complexity": 19
    },
    "libs/docstruct/src/docstruct/geometry/reading_order.py::_order_manifest_body": {
        "lines": 114,
        "complexity": 32,
    },
    "libs/docstruct/src/docstruct/manifest.py::document_invariant_findings": {
        "lines": 132,
        "complexity": 32,
    },
    "libs/docstruct/src/docstruct/regions/classify.py::classify_region": {"complexity": 28},
    "libs/docstruct/src/docstruct/regions/grouping.py::_add_unknown_gaps": {"complexity": 16},
    "libs/docstruct/src/docstruct/regions/grouping.py::_merge_callout_groups": {"complexity": 30},
    "libs/docstruct/src/docstruct/tables/ast.py::_normalize_row": {"complexity": 18},
    "libs/docstruct/src/docstruct/tables/ast.py::_project_section_rows": {"complexity": 17},
    "libs/docstruct/src/docstruct/tables/ast.py::_project_text_rows": {"complexity": 22},
    "libs/docstruct/src/docstruct/tables/ast.py::analyze_table_complexity": {"complexity": 21},
    "libs/docstruct/src/docstruct/tables/ast.py::normalize_table_ast": {"complexity": 29},
    "libs/docstruct/src/docstruct/tables/ast.py::table_ast_from_docling_grid": {
        "lines": 147,
        "complexity": 63,
    },
    "libs/docstruct/src/docstruct/text/inline_math.py::_trimmed": {"complexity": 24},
    "libs/docstruct/src/docstruct/text/inline_math.py::splice_inline_math": {"complexity": 18},
    "libs/docstruct/src/docstruct/text/unicode_repair.py::repair_legacy_unicode": {
        "complexity": 18
    },
    "libs/docstruct/src/docstruct/validation.py::_validate_table_block": {
        "lines": 135,
        "complexity": 31,
    },
    "libs/docstruct/src/docstruct/validation.py::audit_canonical_document.check_accessibility": {
        "complexity": 17
    },
    "libs/sdk/src/acessilia_sdk/cli.py::main": {"complexity": 31},
    "libs/sdk/src/acessilia_sdk/toolbox/results/_model.py::decode": {
        "lines": 109,
        "complexity": 56,
    },
    "libs/sdk/src/acessilia_sdk/toolbox/transport.py::execute_capability": {"complexity": 17},
}


def _allowlist() -> tuple[int, int, dict[str, dict[str, int]]]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return data["max_lines"], data["max_complexity"], data["functions"]


def _parse(path: Path) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(path.read_text(encoding="utf-8"))


def _record_function(found: dict[str, Function], rel: str, fn: Function) -> None:
    """Record ``fn`` under ``rel::qualname``, merging same-scope overloads/branches by max."""
    key = f"{rel}::{fn.qualname}"
    previous = found.get(key)
    if previous is None:
        found[key] = fn
        return
    found[key] = Function(
        path=fn.path,
        name=fn.name,
        lines=max(previous.lines, fn.lines),
        complexity=max(previous.complexity, fn.complexity),
        qualname=fn.qualname,
    )


@pytest.fixture(scope="module")
def repository_functions() -> dict[str, Function]:
    found: dict[str, Function] = {}
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            for fn in iter_functions(_parse(path), rel):
                _record_function(found, rel, fn)
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
    initial_ceilings: dict[str, dict[str, int]] = INITIAL_LEGACY_CEILINGS,
) -> list[str]:
    stale: list[str] = []
    for key, entry in sorted(allowed.items()):
        initial = initial_ceilings.get(key)
        if initial is None:
            stale.append(
                f"  {key}: new allowlist entry is not permitted; decompose the function instead"
            )
            continue
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
        for dim, limit, actual in (
            ("lines", max_lines, fn.lines),
            ("complexity", max_complexity, fn.complexity),
        ):
            if dim not in entry:
                continue
            recorded = entry[dim]
            if dim not in initial:
                stale.append(
                    f"  {key} [{dim}]: dimension was not in the initial allowlist; remove '{dim}'"
                )
            elif recorded > initial[dim]:
                stale.append(
                    f"  {key} [{dim}]: allowlist ceiling {recorded} exceeds initial ceiling {initial[dim]}"
                )
            elif recorded <= limit:
                stale.append(
                    f"  {key} [{dim}]: allowlist ceiling {recorded} is at or below {limit}; remove '{dim}'"
                )
            elif actual <= limit:
                stale.append(
                    f"  {key} [{dim}]: {actual} is at or below {limit}; remove '{dim}'"
                )
            elif actual < recorded:
                stale.append(f"  {key} [{dim}]: {recorded} -> {actual}")
    return stale


def test_the_scanned_roots_exist() -> None:
    missing = [root for root in SCANNED_ROOTS if not (REPO_ROOT / root).is_dir()]

    assert not missing, f"Scanned roots that no longer exist: {missing}"


def test_the_limits_stay_at_100_lines_and_complexity_15() -> None:
    max_lines, max_complexity, _ = _allowlist()

    assert (max_lines, max_complexity) == (MAX_LINES, MAX_COMPLEXITY)


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
    _, _, allowed = _allowlist()
    failures = _check_growth(
        repository_functions,
        allowed,
        max_lines=MAX_LINES,
        max_complexity=MAX_COMPLEXITY,
    )

    assert not failures, (
        "Functions above their complexity or line limit; decompose them instead of raising a ceiling:\n"
        + "\n".join(failures)
    )


def test_the_allowlist_only_shrinks(
    repository_functions: dict[str, Function],
) -> None:
    _, _, allowed = _allowlist()
    stale = _check_stale(
        repository_functions,
        allowed,
        max_lines=MAX_LINES,
        max_complexity=MAX_COMPLEXITY,
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


def test_iter_functions_visits_every_ast_walk_function_across_all_roots() -> None:
    """Every function found by ``ast.walk`` is visited by ``iter_functions``, per root."""
    for root, minimum in MIN_FUNCTIONS_PER_ROOT.items():
        walk_count = 0
        iter_count = 0
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            tree = _parse(path)
            walk_count += sum(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                for node in ast.walk(tree)
            )
            iter_count += sum(1 for _ in iter_functions(tree, path.as_posix()))
        assert iter_count == walk_count, f"{root}: iter_functions={iter_count}, ast.walk={walk_count}"
        assert iter_count >= minimum, f"{root}: expected >= {minimum} functions, found {iter_count}"


def test_core_isolated_guard_matches_architecture_metrics() -> None:
    """The stdlib-only copy in libs/core/tests stays identical to scripts.architecture_metrics."""
    spec = importlib.util.spec_from_file_location("_core_complexity_guard", CORE_GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert (module.MAX_LINES, module.MAX_COMPLEXITY) == (MAX_LINES, MAX_COMPLEXITY)

    core_root = REPO_ROOT / "libs" / "core" / "src" / "acessilia_core"
    for path in sorted(core_root.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = _parse(path)
        from_core_guard = [
            (fn.path, fn.qualname, fn.lines, fn.complexity)
            for fn in module._iter_functions(tree, rel)
        ]
        from_script = [
            (fn.path, fn.qualname, fn.lines, fn.complexity)
            for fn in iter_functions(tree, rel)
        ]
        assert from_core_guard == from_script, f"Parity mismatch on {rel}"


def test_overloaded_or_conditional_definitions_merge_with_max_metrics() -> None:
    tree = ast.parse(
        "from typing import overload\n"
        "@overload\n"
        "def f(x: int) -> int: ...\n"
        "@overload\n"
        "def f(x: str) -> str: ...\n"
        "def f(x):\n"
        "    if isinstance(x, int):\n"
        "        return x + 1\n"
        "    return x\n"
    )
    found: dict[str, Function] = {}
    for fn in iter_functions(tree, "backend/sample.py"):
        _record_function(found, "backend/sample.py", fn)

    assert list(found) == ["backend/sample.py::f"]
    assert found["backend/sample.py::f"].lines == 4
    assert found["backend/sample.py::f"].complexity == 2


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
    initial = {"backend/a.py::f": {"complexity": 17}}

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
            {"backend/a.py::f": fn_ok},
            allowed,
            max_lines=100,
            max_complexity=15,
            initial_ceilings=initial,
        )
        == []
    )
    assert _check_stale(
        {"backend/a.py::f": fn_shrank_cc_still_over},
        allowed,
        max_lines=100,
        max_complexity=15,
        initial_ceilings=initial,
    ) == ["  backend/a.py::f [complexity]: 17 -> 16"]
    assert _check_stale(
        {"backend/a.py::f": fn_shrank_cc_to_limit},
        allowed,
        max_lines=100,
        max_complexity=15,
        initial_ceilings=initial,
    ) == [
        "  backend/a.py::f [complexity]: 15 is at or below 15; remove 'complexity'"
    ]
    assert _check_stale(
        {"backend/a.py::f": fn_ok, "backend/new.py::g": fn_ok},
        {"backend/a.py::f": {"complexity": 17}, "backend/new.py::g": {"complexity": 17}},
        max_lines=100,
        max_complexity=15,
        initial_ceilings=initial,
    ) == [
        "  backend/new.py::g: new allowlist entry is not permitted; decompose the function instead"
    ]
    assert _check_stale(
        {"backend/a.py::f": fn_grew_cc},
        {"backend/a.py::f": {"complexity": 18}},
        max_lines=100,
        max_complexity=15,
        initial_ceilings=initial,
    ) == [
        "  backend/a.py::f [complexity]: allowlist ceiling 18 exceeds initial ceiling 17"
    ]
