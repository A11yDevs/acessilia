"""Reproducible architectural-quality baseline for #656 (PR 1).

The script reads the tracked Python source at a git revision, so the same
baseline can be measured on a past commit without checking it out. It reports
five things for the core, the SDK, docstruct, the backend and the frontend:

- size and approximate cyclomatic complexity per component;
- the component-level import graph and its fan-in/fan-out;
- dependency cycles between components;
- structural duplicates: functions whose normalized AST bodies are identical;
- hotspots: the most complex functions and the largest modules.

It is deliberately stdlib-only and only *diagnoses*: it does not change code,
fail a build or define a ratchet. PR 5 of #656 turns the useful measures into a
CI guard. Run it with::

    python scripts/architecture_quality.py --rev HEAD
    python scripts/architecture_quality.py --rev HEAD --output docs/architecture/quality-baseline.json

The duplicate detector normalizes names, constants, attributes and keywords,
so two functions with the same control flow and different literals group
together. It does not prove semantic equivalence; it only identifies candidates
for the consolidation work of PR 2.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from scripts.architecture_metrics import complexity, python_files  # noqa: E402

#: The component roots measured by the baseline, in report order.
COMPONENTS: dict[str, str] = {
    "core": "libs/core/src/acessilia_core",
    "sdk": "libs/sdk/src/acessilia_sdk",
    "docstruct": "libs/docstruct/src/docstruct",
    "backend": "backend",
    "frontend": "frontend",
}

#: Import roots that identify each component in a file's imports.
COMPONENT_MODULES: dict[str, str] = {
    "acessilia_core": "core",
    "acessilia_sdk": "sdk",
    "docstruct": "docstruct",
    "backend": "backend",
    "frontend": "frontend",
}

#: The minimum non-context AST nodes for a duplicate candidate. A multi-statement
#: function is measured whole, as in the original baseline; a one-statement body
#: is measured on its own so a long signature cannot make a trivial wrapper count.
MIN_DUPLICATE_NODES = 15
#: The baseline keeps only the largest duplicate groups; totals cover all groups.
MAX_DUPLICATE_GROUPS = 40
#: Maximum rows in each hotspot ranking.
MAX_HOTSPOTS = 15
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FunctionRecord:
    """One function and the measures the baseline reports for it."""

    component: str
    path: str
    qualname: str
    lines: int
    complexity: int
    fingerprint: str | None


class _Shape(ast.NodeTransformer):
    """Drop names and literals so equal control flow gets the same fingerprint."""

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = "_"
        node.annotation = None
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        return ast.copy_location(ast.Constant(value="_"), node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        node.attr = "_"
        return self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> ast.AST:
        node.arg = "_"
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = "_"
        node.returns = None
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = "_"
        node.returns = None
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.name = "_"
        return self.generic_visit(node)


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return completed.stdout


def _parse(source: str) -> ast.Module | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            return ast.parse(source)
        except SyntaxError:
            return None


def _resolve_revision(rev: str) -> str:
    try:
        return _git("rev-parse", f"{rev}^{{commit}}").strip()
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"unknown revision: {rev}") from exc


def _component_of(path: str) -> str | None:
    """The component that owns ``path``, or ``None`` outside the scanned roots."""
    for component, root in COMPONENTS.items():
        if path == root or path.startswith(f"{root}/"):
            return component
    return None


def _imported_components(tree: ast.AST, current: str) -> set[str]:
    """First-party components imported by one module, including relative imports."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                component = COMPONENT_MODULES.get(alias.name.split(".")[0])
                if component is not None:
                    found.add(component)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.add(current)
            elif node.module:
                component = COMPONENT_MODULES.get(node.module.split(".")[0])
                if component is not None:
                    found.add(component)
    return found


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _qualname(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: dict[ast.AST, ast.AST],
) -> str:
    names = [node.name]
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(current.name)
        current = parents.get(current)
    return ".".join(reversed(names))


def _body_statements(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """The body without a leading docstring, which is not a logical statement."""
    statements = list(node.body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        return statements[1:]
    return statements


def _node_count(node: ast.AST) -> int:
    """AST nodes that carry structure, excluding the Load/Store/Del context markers."""
    return sum(
        1
        for child in ast.walk(node)
        if not isinstance(child, (ast.Load, ast.Store, ast.Del))
    )


def _fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """A digest of the normalized body, or ``None`` for a body below the node floor.

    A one-statement body is measured on its own, so a long signature cannot
    turn a trivial wrapper into a duplicate. Multi-statement functions keep the
    whole-function floor of the original baseline, so removing the statement
    count exemption does not drop an existing group. Both policies fingerprint
    a substantive one-statement body, so collapsing a forwarding body into one
    statement cannot hide its group (#749).
    """
    statements = _body_statements(node)
    if not statements:
        return None
    nodes = (
        sum(_node_count(statement) for statement in statements)
        if len(statements) == 1
        else _node_count(node)
    )
    if nodes < MIN_DUPLICATE_NODES:
        return None
    body = ast.Module(body=copy.deepcopy(statements), type_ignores=[])
    normalized = _Shape().visit(body)
    dumped = ast.dump(normalized, annotate_fields=False, include_attributes=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _scan(sha: str) -> tuple[dict[str, dict[str, Any]], list[FunctionRecord], list[tuple[str, int, int]], dict[tuple[str, str], int]]:
    """Read every scanned file once and return component metrics and raw evidence."""
    files = python_files(sha, list(COMPONENTS.values()))
    components: dict[str, dict[str, Any]] = {
        component: {
            "files": 0,
            "nonblank_lines": 0,
            "functions": 0,
            "median_function_lines": 0,
            "functions_over_100_lines": 0,
            "functions_complexity_over_15": 0,
        }
        for component in COMPONENTS
    }
    functions: list[FunctionRecord] = []
    file_sizes: list[tuple[str, int, int]] = []
    edges: dict[tuple[str, str], int] = defaultdict(int)

    for path in files:
        component = _component_of(path)
        if component is None:
            continue
        source = _git("show", f"{sha}:{path}")
        tree = _parse(source)
        if tree is None:
            print(f"warning: could not parse {path} at {sha}", file=sys.stderr)
            continue

        nonblank = sum(1 for line in source.splitlines() if line.strip())
        metrics = components[component]
        metrics["files"] += 1
        metrics["nonblank_lines"] += nonblank
        file_sizes.append((path, nonblank, len(source.splitlines())))

        for target in _imported_components(tree, component):
            if target != component:
                edges[(component, target)] += 1

        parents = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            metrics["functions"] += 1
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            functions.append(
                FunctionRecord(
                    component=component,
                    path=path,
                    qualname=_qualname(node, parents),
                    lines=lines,
                    complexity=complexity(node),
                    fingerprint=_fingerprint(node),
                )
            )

    for component, metrics in components.items():
        lengths = sorted(
            function.lines for function in functions if function.component == component
        )
        metrics["median_function_lines"] = statistics.median(lengths) if lengths else 0
        metrics["functions_over_100_lines"] = sum(length > 100 for length in lengths)
        metrics["functions_complexity_over_15"] = sum(
            function.complexity > 15
            for function in functions
            if function.component == component
        )

    return components, functions, file_sizes, dict(edges)


def _duplicate_groups(functions: list[FunctionRecord]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Group functions by structural fingerprint and report the largest groups."""
    by_fingerprint: dict[str, list[FunctionRecord]] = defaultdict(list)
    for function in functions:
        if function.fingerprint is not None:
            by_fingerprint[function.fingerprint].append(function)

    groups = [
        sorted(group, key=lambda function: (function.path, function.qualname))
        for group in by_fingerprint.values()
        if len(group) >= 2
    ]
    groups.sort(key=lambda group: (-len(group), group[0].path, group[0].qualname))
    totals = {
        "groups": len(groups),
        "functions_in_groups": sum(len(group) for group in groups),
        "lines_in_groups": sum(function.lines for group in groups for function in group),
    }
    report = [
        {
            "size": len(group),
            "lines": sum(function.lines for function in group),
            "functions": [
                {
                    "component": function.component,
                    "path": function.path,
                    "qualname": function.qualname,
                    "lines": function.lines,
                }
                for function in group
            ],
        }
        for group in groups[:MAX_DUPLICATE_GROUPS]
    ]
    return report, totals


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """All simple cycles in the component graph, canonically ordered."""
    found: set[tuple[str, ...]] = set()

    def walk(start: str, node: str, path: tuple[str, ...]) -> None:
        for target in sorted(graph.get(node, ())):
            if target == start and len(path) > 1:
                cycle = path
                pivot = cycle.index(min(cycle))
                found.add(cycle[pivot:] + cycle[:pivot])
            elif target not in path:
                walk(start, target, (*path, target))

    for start in sorted(graph):
        walk(start, start, (start,))
    return [list(cycle) for cycle in sorted(found)]


def _hotspots(functions: list[FunctionRecord], file_sizes: list[tuple[str, int, int]]) -> dict[str, list[dict[str, Any]]]:
    """The most complex functions and the largest modules."""
    top_functions = sorted(
        functions,
        key=lambda function: (
            -function.complexity,
            -function.lines,
            function.path,
            function.qualname,
        ),
    )[:MAX_HOTSPOTS]
    top_modules = sorted(file_sizes, key=lambda item: (-item[2], item[0]))[:MAX_HOTSPOTS]
    return {
        "functions": [
            {
                "component": function.component,
                "path": function.path,
                "qualname": function.qualname,
                "complexity": function.complexity,
                "lines": function.lines,
            }
            for function in top_functions
        ],
        "modules": [
            {"path": path, "nonblank_lines": nonblank, "total_lines": total}
            for path, nonblank, total in top_modules
        ],
    }


def collect(rev: str = "HEAD") -> dict[str, Any]:
    """Measure the baseline for ``rev`` and return the JSON-ready payload."""
    sha = _resolve_revision(rev)
    components, functions, file_sizes, edges = _scan(sha)
    targets: dict[str, set[str]] = defaultdict(set)
    sources: dict[str, set[str]] = defaultdict(set)
    for (source, target) in edges:
        sources[target].add(source)
        targets[source].add(target)

    duplicate_groups, duplicate_totals = _duplicate_groups(functions)
    graph = {component: targets.get(component, set()) for component in COMPONENTS}
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scripts/architecture_quality.py",
        "python": platform.python_version(),
        "rev": sha,
        "components": components,
        "dependency_edges": [
            {"from": source, "to": target, "files": count}
            for (source, target), count in sorted(edges.items())
        ],
        "component_coupling": {
            "fan_in": {
                component: len(sources.get(component, set()))
                for component in COMPONENTS
            },
            "fan_out": {
                component: len(targets.get(component, set()))
                for component in COMPONENTS
            },
        },
        "dependency_cycles": _cycles(graph),
        "duplication": {
            "min_nodes": MIN_DUPLICATE_NODES,
            "groups": duplicate_groups,
            "totals": duplicate_totals,
        },
        "hotspots": _hotspots(functions, file_sizes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rev", default="HEAD", help="git revision to measure (default: HEAD)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the JSON baseline there instead of printing it",
    )
    args = parser.parse_args(argv)
    try:
        payload = collect(args.rev)
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
