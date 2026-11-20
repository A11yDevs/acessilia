"""No function of the core exceeds the complexity or line-length limit (#612, #652).

Checked on the ``acessilia_core`` package (``libs/core/src/acessilia_core``)
using the standard-library ``ast`` module alone so this guard runs both in the
main suite and in the isolated ``core alone`` CI job:

- McCabe cyclomatic complexity is at most 15 (1 per function, plus 1 per
  ``if``, loop, ``except``, ``with``, conditional expression, comprehension,
  ``assert``, ``match`` and extra ``and``/``or`` operand, without descending
  into nested functions, lambdas or classes);
- physical span (``end_lineno - lineno + 1``) is at most 100 lines.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "libs" / "core" / "src" / "acessilia_core"

MAX_LINES = 100
MAX_COMPLEXITY = 15

# Intentional stdlib-only copy of scripts/architecture_metrics.py's AST walk:
# the `core alone` CI job runs pytest inside `libs/core` without `scripts/` on
# sys.path. `tests/test_function_complexity.py` checks parity between this module
# and `scripts.architecture_metrics` across every file in `libs/core/src`.
_BRANCHES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.IfExp,
    ast.comprehension,
    ast.Assert,
    ast.Match,
)
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


@dataclass(frozen=True)
class CoreFunction:
    path: str
    qualname: str
    lines: int
    complexity: int


def _complexity(function: ast.AST) -> int:
    total = 1
    nodes = list(ast.iter_child_nodes(function))
    while nodes:
        node = nodes.pop()
        if isinstance(node, _BRANCHES):
            total += 1
        elif isinstance(node, ast.BoolOp):
            total += len(node.values) - 1
        if not isinstance(node, _NESTED_SCOPES):
            nodes.extend(ast.iter_child_nodes(node))
    return total


def _iter_functions(
    node: ast.AST,
    path: str,
    prefix: tuple[str, ...] = (),
) -> Iterator[CoreFunction]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scoped = (*prefix, child.name)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert child.end_lineno is not None
                yield CoreFunction(
                    path=path,
                    qualname=".".join(scoped),
                    lines=child.end_lineno - child.lineno + 1,
                    complexity=_complexity(child),
                )
            yield from _iter_functions(child, path, scoped)
        else:
            yield from _iter_functions(child, path, prefix)


@pytest.fixture(scope="module")
def core_functions() -> list[CoreFunction]:
    functions: list[CoreFunction] = []
    for path in sorted(CORE.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions.extend(_iter_functions(tree, rel))
    return functions


def test_the_scan_sees_the_core_functions(core_functions: list[CoreFunction]) -> None:
    assert len(core_functions) > 700


def test_no_core_function_exceeds_the_line_limit(
    core_functions: list[CoreFunction],
) -> None:
    offenders = [
        f"  {fn.path}::{fn.qualname}: {fn.lines} lines (limit is {MAX_LINES})"
        for fn in core_functions
        if fn.lines > MAX_LINES
    ]

    assert not offenders, (
        "Core functions above the 100-line limit (#612, #652):\n"
        + "\n".join(offenders)
    )


def test_no_core_function_exceeds_the_complexity_limit(
    core_functions: list[CoreFunction],
) -> None:
    offenders = [
        f"  {fn.path}::{fn.qualname}: complexity {fn.complexity} (limit is {MAX_COMPLEXITY})"
        for fn in core_functions
        if fn.complexity > MAX_COMPLEXITY
    ]

    assert not offenders, (
        "Core functions above McCabe complexity 15 (#612, #652):\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(x):\n    return x\n", [("f", 2, 1)]),
        (
            "def f(a, b, c):\n"
            "    if a and b or c:\n"
            "        for x in [y for y in a if y]:\n"
            "            with ctx():\n"
            "                assert x\n"
            "    return 1 if a else 0\n",
            [("f", 6, 9)],
        ),
        (
            "class C:\n"
            "    def outer(self, x):\n"
            "        fn = lambda y: y if y else 0\n"
            "        def inner(z):\n"
            "            if z:\n"
            "                return 1\n"
            "            return 0\n"
            "        return fn(x) + inner(x)\n",
            [("C.outer", 7, 1), ("C.outer.inner", 4, 2)],
        ),
    ],
)
def test_complexity_and_scoped_qualnames(
    source: str, expected: list[tuple[str, int, int]]
) -> None:
    tree = ast.parse(source)
    measured = [
        (fn.qualname, fn.lines, fn.complexity)
        for fn in _iter_functions(tree, "sample.py")
    ]
    assert measured == expected
