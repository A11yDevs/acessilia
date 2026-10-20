"""Core modules that bridge to docstruct stay bridges (#203).

When a pure algorithm moves from the core to docstruct, the core module keeps
its import path for existing consumers. Each such module is registered here
in one of two categories:

- ``reexport``: only imports from docstruct and ``__all__``. No definitions.
- ``compatibility_adapter``: may also define small wrappers that delegate to
  docstruct and add what belongs to the core (i18n, file writes, Toolbox
  calls, the core's historical defaults). It must not reimplement the
  structural algorithm.

A last check compares function bodies across the core and docstruct, so a
copy of a docstruct function cannot hide in a module that is not registered.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCSTRUCT = ROOT / "libs" / "docstruct" / "src" / "docstruct"

REEXPORT = "reexport"
ADAPTER = "compatibility_adapter"

BRIDGES = {
    "backend/export/filters/pandoc_filters.py": REEXPORT,
    "backend/pipeline/pandoc_ast_builder.py": REEXPORT,
    "backend/pipeline/sanitizer.py": REEXPORT,
    "backend/pipeline/semantic_rules.py": REEXPORT,
    "backend/pipeline/verbosity_manager.py": REEXPORT,
    "backend/tools/code_tools.py": REEXPORT,
    "backend/tools/region_classifier.py": REEXPORT,
    "backend/tools/text_processor.py": REEXPORT,
    "backend/export/renderers/html_renderer.py": ADAPTER,
    "backend/export/renderers/txt_renderer.py": ADAPTER,
    "backend/pipeline/canonical_builder.py": ADAPTER,
    "backend/pipeline/table_ast.py": ADAPTER,
    "backend/pipeline/validators.py": ADAPTER,
    "backend/tools/formula_tools.py": ADAPTER,
}

#: A bridge says so in its docstring; this keeps the registry complete.
BRIDGE_MARKER = "migrated to docstruct"

#: Largest function an adapter may define, in statements. Wrappers that add
#: i18n, a file write or a Toolbox call stay well below it; a reimplemented
#: algorithm does not.
MAX_ADAPTER_STATEMENTS = 15

#: Function bodies smaller than this are too generic to call a copy.
MIN_COMPARED_NODES = 25

#: Copies of docstruct functions still in the core, each removed by a later
#: #203 step. Remove the entry with the copy; the test fails on stale entries.
KNOWN_COPIES = {
    "backend/agents/pddl_orchestrator.py:_rows_from_table_ast",
}


def _tree(relative: str) -> ast.Module:
    return ast.parse((ROOT / relative).read_text(encoding="utf-8"))


def _docstruct_imports(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").split(".")[0] == "docstruct"
        for node in tree.body
    )


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def _is_all(node: ast.stmt) -> bool:
    return isinstance(node, ast.Assign) and [
        getattr(target, "id", None) for target in node.targets
    ] == ["__all__"]


def _statement_count(function: ast.AST) -> int:
    return sum(isinstance(node, ast.stmt) for node in ast.walk(function)) - 1


def test_every_bridge_is_registered() -> None:
    marked = {
        path.relative_to(ROOT).as_posix()
        for base in ("backend", "frontend")
        for path in (ROOT / base).rglob("*.py")
        if BRIDGE_MARKER in (ast.get_docstring(ast.parse(path.read_text("utf-8"))) or "")
    }

    assert marked == set(BRIDGES)


@pytest.mark.parametrize("module", sorted(BRIDGES))
def test_bridge_imports_from_docstruct(module: str) -> None:
    assert _docstruct_imports(_tree(module))


@pytest.mark.parametrize(
    "module", sorted(path for path, kind in BRIDGES.items() if kind == REEXPORT)
)
def test_reexport_defines_nothing(module: str) -> None:
    offenders = [
        f"line {node.lineno}: {type(node).__name__}"
        for node in _tree(module).body
        if not (
            isinstance(node, (ast.Import, ast.ImportFrom))
            or _is_docstring(node)
            or _is_all(node)
        )
    ]

    assert offenders == []


@pytest.mark.parametrize(
    "module", sorted(path for path, kind in BRIDGES.items() if kind == ADAPTER)
)
def test_adapter_only_wraps(module: str) -> None:
    tree = _tree(module)
    imported = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    functions = [
        node
        for top in tree.body
        for node in ([top] if not isinstance(top, ast.ClassDef) else top.body)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    offenders = [
        f"{function.name}: {_statement_count(function)} statements"
        for function in functions
        if _statement_count(function) > MAX_ADAPTER_STATEMENTS
    ]
    offenders += [
        f"{function.name}: while loop"
        for function in functions
        if any(isinstance(node, ast.While) for node in ast.walk(function))
    ]
    # A class in an adapter specializes a docstruct extension point.
    offenders += [
        f"class {node.name} does not extend an imported base"
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and not any(getattr(base, "id", None) in imported for base in node.bases)
    ]

    assert offenders == []


def _function_bodies(paths) -> dict[str, list[str]]:
    """Function body dumps (docstring dropped) -> where they are defined."""
    bodies: dict[str, list[str]] = {}
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = node.body[1:] if node.body and _is_docstring(node.body[0]) else node.body
            module = ast.Module(body=body, type_ignores=[])
            if sum(1 for _ in ast.walk(module)) < MIN_COMPARED_NODES:
                continue
            bodies.setdefault(ast.dump(module), []).append(f"{relative}:{node.name}")
    return bodies


def test_core_holds_no_copy_of_a_docstruct_function() -> None:
    library = _function_bodies(DOCSTRUCT.rglob("*.py"))
    core = _function_bodies(
        path for base in ("backend", "frontend") for path in (ROOT / base).rglob("*.py")
    )

    copies = {
        location
        for body, locations in core.items()
        if body in library
        for location in locations
    }

    assert copies == KNOWN_COPIES


# --- Behaviour kept by the bridges -------------------------------------------


def test_verbosity_manager_keeps_its_api_and_defaults() -> None:
    from backend.pipeline import verbosity_manager

    assert verbosity_manager.normalize_profile("pdf")["verbosity"] == ["basic", "detailed"]
    # Unknown profiles fall back to txt; unknown modes to "detailed".
    assert verbosity_manager.normalize_profile("epub") == verbosity_manager.OUTPUT_PROFILES["txt"]
    assert verbosity_manager.verbosity_for_mode("detalhado") == "technical"
    assert verbosity_manager.verbosity_for_mode("other") == "detailed"
    # A caller may change the profile it gets without changing the table.
    verbosity_manager.normalize_profile("html")["verbosity"].clear()
    assert verbosity_manager.OUTPUT_PROFILES["html"]["verbosity"] == [
        "basic", "detailed", "technical",
    ]
    blocks = [{"verbosity": "technical"}, {"verbosity": "basic"}, {}]
    assert verbosity_manager.filter_blocks_for_profile(blocks, "txt") == [
        {"verbosity": "basic"},
        {},
    ]
    assert verbosity_manager.filter_blocks_for_profile([], "html") == []
