"""Size and approximate complexity of the Python code under some roots of a git revision.

Used by #470's phase 5 evaluation (docs/architecture/core-sdk-docstruct-evaluation.md)
to compare the core, the SDK and docstruct before and after the refactoring.
It reads the files from ``git`` at ``--rev``, so any past revision can be
measured without checking it out.

The complexity is McCabe's, approximated on the AST: 1 per function, plus 1
per branch (``if``, loops, ``except``, ``with``, conditional expressions,
comprehensions, ``assert``, ``match``) and per extra operand of ``and``/``or``.
Nested functions, lambdas and classes are not descended into.

    python scripts/architecture_metrics.py --rev HEAD libs/core/src
    python scripts/architecture_metrics.py --rev HEAD --tests tests libs/core/tests
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_BRANCHES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With,
    ast.AsyncWith, ast.IfExp, ast.comprehension, ast.Assert, ast.Match,
)
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


@dataclass(frozen=True)
class Function:
    path: str
    name: str
    lines: int
    complexity: int


def complexity(function: ast.AST) -> int:
    """McCabe's complexity of ``function``, approximated on its AST."""
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


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def python_files(rev: str, roots: list[str]) -> list[str]:
    listed = _git("ls-tree", "-r", "--name-only", rev, "--", *roots).split()
    return sorted(path for path in listed if path.endswith(".py"))


def _parse(source: str) -> ast.Module | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            return ast.parse(source)
        except SyntaxError:
            return None


def measure(rev: str, roots: list[str]) -> dict:
    """Files, non-blank lines, functions and their length and complexity."""
    functions: list[Function] = []
    nonblank = 0
    sizes: dict[str, int] = {}
    files = python_files(rev, roots)
    for path in files:
        source = _git("show", f"{rev}:{path}")
        nonblank += sum(1 for line in source.splitlines() if line.strip())
        sizes[path] = len(source.splitlines())
        tree = _parse(source)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(
                    Function(path, node.name, node.end_lineno - node.lineno + 1, complexity(node))
                )
    lengths = sorted(function.lines for function in functions)
    return {
        "rev": rev,
        "roots": roots,
        "files": len(files),
        "nonblank_lines": nonblank,
        "functions": len(functions),
        "median_function_lines": statistics.median(lengths) if lengths else 0,
        "functions_over_100_lines": sum(length > 100 for length in lengths),
        "functions_complexity_over_15": sum(f.complexity > 15 for f in functions),
        "most_complex": [
            [f.path, f.name, f.complexity, f.lines]
            for f in sorted(functions, key=lambda f: (-f.complexity, f.path))[:5]
        ],
        "largest_files": sorted(sizes.items(), key=lambda item: -item[1])[:3],
    }


def count_tests(rev: str, roots: list[str]) -> dict:
    """Test files (``test*.py``) and the test functions they define."""
    files = [path for path in python_files(rev, roots) if Path(path).name.startswith("test")]
    count = 0
    for path in files:
        tree = _parse(_git("show", f"{rev}:{path}"))
        if tree is None:
            continue
        count += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
            for node in ast.walk(tree)
        )
    return {"rev": rev, "roots": roots, "test_files": len(files), "test_functions": count}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="+", help="directories to measure, relative to the repository")
    parser.add_argument("--rev", default="HEAD", help="git revision to read (default: HEAD)")
    parser.add_argument("--tests", action="store_true", help="count test functions instead")
    args = parser.parse_args(argv)
    result = count_tests(args.rev, args.roots) if args.tests else measure(args.rev, args.roots)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
