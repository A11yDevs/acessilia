"""The script behind #470's phase 5 measurements (scripts/architecture_metrics.py)."""

from __future__ import annotations

import ast
import json

from scripts import architecture_metrics as metrics


def _complexity(source: str) -> int:
    return metrics.complexity(ast.parse(source).body[0])


def test_complexity_counts_branches_and_boolean_operands() -> None:
    assert _complexity("def f():\n    return 1\n") == 1
    assert _complexity("def f(x):\n    if x:\n        return 1\n    return 2\n") == 2
    assert _complexity("def f(a, b, c):\n    if a and b or c:\n        pass\n") == 4
    assert _complexity("def f(xs):\n    for x in xs:\n        try:\n            pass\n        except ValueError:\n            pass\n") == 3
    assert _complexity("def f(xs):\n    return [x for x in xs if x]\n") == 2


def test_complexity_does_not_count_nested_scopes() -> None:
    source = (
        "def outer(x):\n"
        "    def inner(y):\n"
        "        if y:\n"
        "            return 1\n"
        "        return 2\n"
        "    cb = lambda z: 1 if z else 0\n"
        "    class Inner:\n"
        "        def method(self, w):\n"
        "            return w if w else 0\n"
        "    if x:\n"
        "        return inner(x)\n"
        "    return 0\n"
    )
    module = ast.parse(source)
    outer = module.body[0]
    inner = outer.body[0]
    inner_method = outer.body[2].body[0]
    assert metrics.complexity(outer) == 2
    assert metrics.complexity(inner) == 2
    assert metrics.complexity(inner_method) == 2


def test_it_measures_a_root_of_the_current_revision(capsys) -> None:
    assert metrics.main(["--rev", "HEAD", "libs/sdk/src"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["files"] > 0 and result["nonblank_lines"] > 0 and result["functions"] > 0
    assert {"functions_over_100_lines", "functions_complexity_over_15", "most_complex"} <= set(result)


def test_it_counts_test_functions(capsys) -> None:
    assert metrics.main(["--rev", "HEAD", "--tests", "libs/core/tests"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["test_files"] >= 1 and result["test_functions"] >= 1
