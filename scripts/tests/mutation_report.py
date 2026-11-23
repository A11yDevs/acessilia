"""Run a bounded mutation experiment and derive test subsumption (#644).

The experiment mutates one small module with deterministic AST operators, runs
a focused test target against each mutant in an isolated copy of the package,
and records which tests detected which mutation. From that matrix it derives:

* the mutation score of the selected tests;
* mutants that survive or belong to uncovered lines;
* test subsumption: A subsumes B when every mutant B kills, A also kills;
* mutants detected by exactly one test.

This is a proof of concept, not a CI gate. ``mutmut`` and similar tools remain
candidates for periodic, larger runs; this harness keeps the experiment
dependency-free, reproducible and small enough to review.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.test_report import parse_report  # noqa: E402

SCHEMA_VERSION = 1

COMPARE_SWAPS: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}
BOOL_SWAPS: dict[type[ast.boolop], type[ast.boolop]] = {
    ast.And: ast.Or,
    ast.Or: ast.And,
}
AUG_SWAPS: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
}

#: Operators the harness can generate; ``--operators`` filters them.
OPERATORS = ("compare", "boolop", "bool-constant", "remove-not", "negate-condition", "augassign")


@dataclass(frozen=True)
class Mutant:
    id: str
    operator: str
    line: int
    column: int
    description: str
    node_type: str
    index: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MutantResult:
    mutant: Mutant
    status: str
    killers: list[str] = field(default_factory=list)
    seconds: float = 0.0
    exit_code: int | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            **self.mutant.to_dict(),
            "status": self.status,
            "killers": self.killers,
            "seconds": round(self.seconds, 3),
            "exit_code": self.exit_code,
            "error": self.error,
        }


def _node_at(tree: ast.AST, node_type: str, line: int, column: int) -> ast.AST:
    for node in ast.walk(tree):
        if (
            type(node).__name__ == node_type
            and getattr(node, "lineno", None) == line
            and getattr(node, "col_offset", None) == column
        ):
            return node
    raise LookupError(f"no {node_type} at {line}:{column}")


def _parents(tree: ast.AST) -> dict[ast.AST, tuple[ast.AST, str, int | None]]:
    parents: dict[ast.AST, tuple[ast.AST, str, int | None]] = {}
    for parent in ast.walk(tree):
        for name, value in ast.iter_fields(parent):
            if isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, ast.AST):
                        parents[item] = (parent, name, index)
            elif isinstance(value, ast.AST):
                parents[value] = (parent, name, None)
    return parents


def _replace(tree: ast.AST, target: ast.AST, replacement: ast.AST) -> None:
    parent, name, index = _parents(tree)[target]
    if index is None:
        setattr(parent, name, replacement)
    else:
        getattr(parent, name)[index] = replacement


def _add(
    mutants: list[tuple[str, int, int, str, str, int]],
    operator: str,
    node: ast.AST,
    description: str,
    index: int = 0,
) -> None:
    mutants.append(
        (
            operator,
            int(getattr(node, "lineno", 0)),
            int(getattr(node, "col_offset", 0)),
            description,
            type(node).__name__,
            index,
        )
    )


def _mutations_for_node(node: ast.AST) -> list[tuple[str, int, int, str, str, int]]:
    mutants: list[tuple[str, int, int, str, str, int]] = []
    if isinstance(node, ast.Compare):
        for index, operator in enumerate(node.ops):
            swap = COMPARE_SWAPS.get(type(operator))
            if swap is not None:
                _add(
                    mutants,
                    "compare",
                    node,
                    f"{type(operator).__name__} -> {swap.__name__}",
                    index,
                )
    elif isinstance(node, ast.BoolOp):
        swap = BOOL_SWAPS.get(type(node.op))
        if swap is not None:
            _add(mutants, "boolop", node, f"{type(node.op).__name__} -> {swap.__name__}")
    elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
        _add(mutants, "bool-constant", node, f"{node.value} -> {not node.value}")
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        _add(mutants, "remove-not", node, "remove not")
    elif isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
        _add(mutants, "negate-condition", node, "negate condition")
    elif isinstance(node, ast.AugAssign):
        swap = AUG_SWAPS.get(type(node.op))
        if swap is not None:
            _add(mutants, "augassign", node, f"{type(node.op).__name__} -> {swap.__name__}")
    return mutants


def generate_mutants(source: str, *, operators: Sequence[str] = OPERATORS) -> list[Mutant]:
    """Deterministic mutations of one module, sorted by position."""
    tree = ast.parse(source)
    enabled = set(operators)
    rows = [
        row
        for node in ast.walk(tree)
        for row in _mutations_for_node(node)
        if row[0] in enabled
    ]
    rows.sort(key=lambda row: (row[1], row[2], row[0], row[5]))
    return [
        Mutant(
            id=f"M{index:03d}",
            operator=operator,
            line=line,
            column=column,
            description=description,
            node_type=node_type,
            index=op_index,
        )
        for index, (operator, line, column, description, node_type, op_index) in enumerate(
            rows, start=1
        )
    ]


def mutate_source(source: str, mutant: Mutant) -> str:
    """Apply exactly one mutation and return the unparsed module."""
    tree = copy.deepcopy(ast.parse(source))
    if mutant.node_type == "Compare":
        node = _node_at(tree, mutant.node_type, mutant.line, mutant.column)
        assert isinstance(node, ast.Compare)
        node.ops[mutant.index] = COMPARE_SWAPS[type(node.ops[mutant.index])]()
    elif mutant.node_type == "BoolOp":
        node = _node_at(tree, mutant.node_type, mutant.line, mutant.column)
        assert isinstance(node, ast.BoolOp)
        node.op = BOOL_SWAPS[type(node.op)]()
    elif mutant.node_type == "Constant":
        node = _node_at(tree, mutant.node_type, mutant.line, mutant.column)
        assert isinstance(node, ast.Constant) and isinstance(node.value, bool)
        node.value = not node.value
    elif mutant.node_type == "UnaryOp":
        node = _node_at(tree, mutant.node_type, mutant.line, mutant.column)
        assert isinstance(node, ast.UnaryOp)
        _replace(tree, node, node.operand)
    elif mutant.node_type in ("If", "While", "IfExp", "Assert"):
        node = _node_at(tree, mutant.node_type, mutant.line, mutant.column)
        assert isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert))
        node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
    elif mutant.node_type == "AugAssign":
        node = _node_at(tree, mutant.node_type, mutant.line, mutant.column)
        assert isinstance(node, ast.AugAssign)
        node.op = AUG_SWAPS[type(node.op)]()
    else:
        raise ValueError(f"unsupported mutant node {mutant.node_type}")
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def _run_pytest(
    tests: Sequence[str],
    *,
    suite: Path,
    junit: Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
    known_tests: set[str] | None = None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        *tests,
        "-q",
        "-p",
        "no:cacheprovider",
        f"--timeout={timeout_seconds}",
        f"--junitxml={junit}",
    ]
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=suite,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds + 30,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "seconds": time.monotonic() - start,
            "exit_code": None,
            "killers": [],
            "error": str(exc),
        }
    seconds = time.monotonic() - start
    if not junit.is_file():
        return {
            "status": "invalid",
            "seconds": seconds,
            "exit_code": completed.returncode,
            "killers": [],
            "error": (completed.stdout + completed.stderr)[-2000:],
        }
    result = parse_report(junit, "mutation", root=suite)
    test_ids = sorted(result.cases)
    killers = sorted(
        case.nodeid
        for case in result.cases.values()
        if case.outcome in ("failed", "error")
    )
    if known_tests is not None:
        # Collection errors become module-level pseudo-cases that are not
        # tests. They must not enter killing_tests or subsumption.
        killers = [killer for killer in killers if killer in known_tests]
    status = "killed" if killers else "survived"
    if not killers and completed.returncode != 0:
        status = "invalid"
    return {
        "status": status,
        "seconds": seconds,
        "exit_code": completed.returncode,
        "killers": killers,
        "test_ids": test_ids,
        "error": "",
    }


def _copy_package(source_root: Path, destination: Path) -> Path:
    target = destination / "src"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source_root,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return target


def _mutant_env(temp_src: Path) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(temp_src) + (os.pathsep + existing if existing else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_experiment(
    mutants: Sequence[Mutant],
    *,
    source: str,
    module_relative: Path,
    source_root: Path,
    suite: Path,
    tests: Sequence[str],
    timeout_seconds: int = 60,
) -> tuple[dict[str, Any], list[MutantResult]]:
    """Run the baseline and every mutant in an isolated package copy."""
    with tempfile.TemporaryDirectory(prefix="acessilia-mutation-") as raw:
        temp = Path(raw)
        temp_src = _copy_package(source_root, temp)
        target = temp_src / module_relative
        env = _mutant_env(temp_src)
        baseline_junit = temp / "baseline.xml"
        baseline = _run_pytest(
            tests,
            suite=suite,
            junit=baseline_junit,
            timeout_seconds=timeout_seconds,
            env=env,
        )
        if baseline["status"] != "survived":
            raise RuntimeError(f"the selected tests do not pass before mutation: {baseline}")
        known_tests = set(baseline.pop("test_ids", []))
        results: list[MutantResult] = []
        for mutant in mutants:
            target.write_text(mutate_source(source, mutant), encoding="utf-8")
            junit = temp / f"{mutant.id}.xml"
            outcome = _run_pytest(
                tests,
                suite=suite,
                junit=junit,
                timeout_seconds=timeout_seconds,
                env=env,
                known_tests=known_tests,
            )
            results.append(
                MutantResult(
                    mutant=mutant,
                    status=outcome["status"],
                    killers=outcome["killers"],
                    seconds=outcome["seconds"],
                    exit_code=outcome["exit_code"],
                    error=outcome["error"],
                )
            )
    return baseline, results


def load_covered_lines(coverage_file: Path | None, module: Path) -> set[int] | None:
    if coverage_file is None or not coverage_file.is_file():
        return None
    from coverage import CoverageData

    data = CoverageData(basename=str(coverage_file))
    data.read()
    lines = data.lines(str(module.resolve()))
    return None if lines is None else set(lines)


def _kill_sets(results: Sequence[MutantResult]) -> dict[str, set[str]]:
    kills: dict[str, set[str]] = defaultdict(set)
    for result in results:
        if result.status != "killed":
            continue
        for killer in result.killers:
            kills[killer].add(result.mutant.id)
    return dict(kills)


def _overlap_similarity(overlap: dict[str, Any] | None) -> dict[frozenset[str], float]:
    if not overlap:
        return {}
    return {
        frozenset((pair["test_a"], pair["test_b"])): float(pair["similarity"])
        for pair in overlap.get("pairs", [])
    }


def subsumption_pairs(
    results: Sequence[MutantResult],
    *,
    overlap: dict[str, Any] | None = None,
    limit: int | None = 50,
) -> list[dict[str, Any]]:
    """Pairs where every mutant B kills, A kills too."""
    kills = _kill_sets(results)
    similarities = _overlap_similarity(overlap)
    pairs: list[dict[str, Any]] = []
    for subsumed in sorted(kills):
        for subsumer in sorted(kills):
            if subsumed == subsumer:
                continue
            if not kills[subsumed] <= kills[subsumer]:
                continue
            equal = kills[subsumed] == kills[subsumer]
            if equal and subsumer > subsumed:
                continue
            pairs.append(
                {
                    "subsumer": subsumer,
                    "subsumed": subsumed,
                    "mutants": len(kills[subsumed]),
                    "equal": equal,
                    "coverage_similarity": similarities.get(
                        frozenset((subsumer, subsumed))
                    ),
                }
            )
    pairs.sort(key=lambda item: (item["equal"], -item["mutants"], item["subsumer"]))
    return pairs if limit is None else pairs[:limit]


def exclusive_mutants(results: Sequence[MutantResult], limit: int = 20) -> list[dict[str, Any]]:
    kills = _kill_sets(results)
    exclusive = []
    for test, mutants in kills.items():
        only = [
            result.mutant.id
            for result in results
            if result.mutant.id in mutants
            and sum(result.mutant.id in other for other in kills.values()) == 1
        ]
        if only:
            exclusive.append({"test": test, "mutants": only})
    exclusive.sort(key=lambda item: (-len(item["mutants"]), item["test"]))
    return exclusive[:limit]


def build_report(
    *,
    results: Sequence[MutantResult],
    module: Path,
    tests: Sequence[str],
    baseline: dict[str, Any] | None,
    covered_lines: set[int] | None,
    overlap: dict[str, Any] | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Classify mutants and derive the mutation/subsumption summary."""
    for result in results:
        if result.status in ("killed", "timeout", "invalid"):
            continue
        if covered_lines is not None and result.mutant.line not in covered_lines:
            result.status = "uncovered"
    killed = sum(result.status == "killed" for result in results)
    survived = sum(result.status == "survived" for result in results)
    timeout = sum(result.status == "timeout" for result in results)
    uncovered = sum(result.status == "uncovered" for result in results)
    invalid = sum(result.status == "invalid" for result in results)
    covered_mutants = killed + survived + timeout
    kills = _kill_sets(results)
    limit = int(settings.get("max_subsumption", 50))
    all_subsumption = subsumption_pairs(results, overlap=overlap, limit=None)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "mutation-report",
        "module": str(module),
        "tests": list(tests),
        "settings": settings,
        "baseline": baseline,
        "summary": {
            "total": len(results),
            "killed": killed,
            "survived": survived,
            "timeout": timeout,
            "uncovered": uncovered,
            "invalid": invalid,
            "covered_mutants": covered_mutants,
            "mutation_score": round(killed / covered_mutants, 4) if covered_mutants else 0.0,
            "killing_tests": len(kills),
            "subsumption_total": len(all_subsumption),
            "subsumption_examples": min(limit, len(all_subsumption)),
            "equivalent_mutants": "not identified automatically",
        },
        "mutants": [result.to_dict() for result in results],
        "subsumption": all_subsumption[:limit],
        "exclusive": exclusive_mutants(results),
    }


def render_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "## Mutation experiment (#644)",
        "",
        f"Module: `{report['module']}`",
        "",
        f"Tests: {', '.join(f'`{test}`' for test in report['tests'])}",
        "",
        "| Total | Killed | Survived | Timeout | Uncovered | Invalid | Mutation score |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary['total']} | {summary['killed']} | {summary['survived']} "
            f"| {summary['timeout']} | {summary['uncovered']} | {summary['invalid']} "
            f"| {summary['mutation_score']:.1%} |"
        ),
        "",
        (
            "Equivalent mutants are not identified automatically: a surviving "
            "mutant still needs a manual judgement."
        ),
        "",
        "### Mutants",
        "",
        "| Id | Line | Mutation | Status | Killed by |",
        "|---|---:|---|---|---|",
    ]
    for mutant in report["mutants"]:
        killers = ", ".join(f"`{killer}`" for killer in mutant["killers"]) or "—"
        lines.append(
            f"| {mutant['id']} | {mutant['line']} | {mutant['description']} "
            f"| {mutant['status']} | {killers} |"
        )
    if not report["mutants"]:
        lines.append("| — | — | — | — | — |")

    lines += [
        "",
        f"### Test subsumption (top {summary.get('subsumption_examples', 0)} of "
        f"{summary.get('subsumption_total', 0)})",
        "",
        (
            "A subsumes B when every mutant B kills, A also kills. High "
            "coverage similarity does not imply this relation. Both the JSON "
            "and this table are capped; the total is in the summary."
        ),
        "",
        "| Subsumer | Subsumed | Mutants | Equal sets | Coverage Jaccard |",
        "|---|---|---:|---|---:|",
    ]
    for pair in report["subsumption"]:
        similarity = pair["coverage_similarity"]
        similarity_text = f"{similarity:.3f}" if isinstance(similarity, float) else "—"
        lines.append(
            f"| `{pair['subsumer']}` | `{pair['subsumed']}` | {pair['mutants']} "
            f"| {'yes' if pair['equal'] else 'no'} | {similarity_text} |"
        )
    if not report["subsumption"]:
        lines.append("| — | — | — | — | — |")

    lines += [
        "",
        "### Mutants detected by exactly one test",
        "",
        "| Test | Mutants |",
        "|---|---|",
    ]
    for item in report["exclusive"]:
        lines.append(f"| `{item['test']}` | {', '.join(item['mutants'])} |")
    if not report["exclusive"]:
        lines.append("| — | — |")
    return "\n".join(lines) + "\n"


def _read_module(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--tests", action="append", required=True)
    parser.add_argument("--suite", type=Path, default=Path("."))
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--coverage-file", type=Path)
    parser.add_argument("--overlap", type=Path)
    parser.add_argument("--operators", default=",".join(OPERATORS))
    parser.add_argument("--max-mutants", type=int, default=40)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-subsumption", type=int, default=50)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument(
        "--list-mutants",
        action="store_true",
        help="print the generated mutants and exit without running them",
    )
    args = parser.parse_args(argv)

    def _anchored(path: Path | None) -> Path | None:
        if path is None:
            return None
        return path if path.is_absolute() else (ROOT / path)

    module = _anchored(args.module)
    assert module is not None
    source_root = _anchored(args.source_root)
    assert source_root is not None
    suite = _anchored(args.suite)
    assert suite is not None
    coverage_file = _anchored(args.coverage_file)
    overlap_file = _anchored(args.overlap)
    output = _anchored(args.output)
    summary_path = _anchored(args.summary)
    if not module.is_file():
        print(f"error: {module} does not exist", file=sys.stderr)
        return 2
    try:
        module_relative = module.relative_to(source_root)
    except ValueError:
        print(f"error: {module} is not under {source_root}", file=sys.stderr)
        return 2
    source = _read_module(module)
    operators = [name.strip() for name in args.operators.split(",") if name.strip()]
    unknown = sorted(set(operators) - set(OPERATORS))
    if unknown:
        print(f"error: unknown operators: {', '.join(unknown)}", file=sys.stderr)
        return 2
    mutants = generate_mutants(source, operators=operators)[: args.max_mutants]

    if args.list_mutants:
        for mutant in mutants:
            print(
                f"{mutant.id} line {mutant.line}: {mutant.description} ({mutant.operator})"
            )
        return 0

    if output is None:
        print("error: --output is required unless --list-mutants is used", file=sys.stderr)
        return 2
    try:
        baseline, results = run_experiment(
            mutants,
            source=source,
            module_relative=module_relative,
            source_root=source_root,
            suite=suite,
            tests=args.tests,
            timeout_seconds=args.timeout,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        module_label = module.relative_to(ROOT)
    except ValueError:
        module_label = module
    report = build_report(
        results=results,
        module=module_label,
        tests=args.tests,
        baseline=baseline,
        covered_lines=load_covered_lines(coverage_file, module),
        overlap=_load_json(overlap_file),
        settings={
            "operators": operators,
            "max_mutants": args.max_mutants,
            "timeout_seconds": args.timeout,
            "max_subsumption": args.max_subsumption,
        },
    )
    summary = render_summary(report)
    print(summary)
    _write(output, json.dumps(report, indent=2) + "\n")
    if summary_path:
        _write(summary_path, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
