"""Core modules that bridge to docstruct stay bridges (#203).

When a pure algorithm moves from the core to docstruct, the core's callers
import docstruct directly. A core module may still bridge to docstruct only as
a ``compatibility_adapter``: small wrappers that delegate to docstruct and add
what belongs to the core (i18n, file writes, Toolbox calls, the core's
historical defaults), never a reimplementation of the structural algorithm.
Each such module is registered here.

The ``reexport`` category, modules made only of docstruct imports, was closed
when its last module (``backend/tools/code_tools.py``) went (#191). A module
like that is now rejected wherever it appears in ``backend/`` or ``frontend/``
(where the core's code lives), by its imports, whether or not its docstring
says it was "migrated to docstruct".

A last check compares function bodies across the core and docstruct, so a
copy of a docstruct function cannot hide in a module that is not registered.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCSTRUCT = ROOT / "libs" / "docstruct" / "src" / "docstruct"

ADAPTER = "compatibility_adapter"

BRIDGES = {
    "backend/core/export/renderers/html_renderer.py": ADAPTER,
    "backend/core/export/renderers/txt_renderer.py": ADAPTER,
    "backend/core/pipeline/canonical_builder.py": ADAPTER,
    "backend/core/pipeline/table_ast.py": ADAPTER,
    "backend/core/pipeline/validators.py": ADAPTER,
    "backend/core/formula_tools.py": ADAPTER,
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
KNOWN_COPIES: set[str] = set()


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
    """``__all__ = ...``, ``__all__: list[str] = ...`` or ``__all__ += ...``."""
    if isinstance(node, ast.Assign):
        return [getattr(target, "id", None) for target in node.targets] == ["__all__"]
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return getattr(node.target, "id", None) == "__all__"
    return False


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


def _is_pure_docstruct_reexport(tree: ast.Module) -> bool:
    """A module of docstruct imports and nothing else (docstring, ``__all__`` and
    ``from __future__`` aside): a re-export bridge."""
    imports = [
        node for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and getattr(node, "module", None) != "__future__"
    ]
    others = [
        node for node in tree.body
        if not (isinstance(node, (ast.Import, ast.ImportFrom)) or _is_docstring(node) or _is_all(node))
    ]
    return bool(imports) and not others and all(_imports_only_docstruct(node) for node in imports)


def _imports_only_docstruct(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.ImportFrom):
        return node.level == 0 and (node.module or "").split(".")[0] == "docstruct"
    return all(alias.name.split(".")[0] == "docstruct" for alias in node.names)


def test_no_module_is_a_pure_docstruct_reexport() -> None:
    """The re-export category is closed (#191): callers import docstruct directly."""
    offenders = sorted(
        path.relative_to(ROOT).as_posix()
        for base in ("backend", "frontend")
        for path in (ROOT / base).rglob("*.py")
        if _is_pure_docstruct_reexport(ast.parse(path.read_text("utf-8")))
    )

    assert offenders == [], f"modules that only re-export docstruct: {offenders}"


def test_the_reexport_check_finds_a_shim() -> None:
    shim = ast.parse(
        '"""Moved."""\nfrom __future__ import annotations\n\n'
        "from docstruct.text.code_reflow import normalize_code_text  # noqa: F401\n\n"
        '__all__ = ["normalize_code_text"]\n'
    )
    adapter = ast.parse("from docstruct.text import x\n\ndef y():\n    return x()\n")

    annotated = ast.parse(
        '"""Temporary shim."""\nfrom docstruct.text.code_reflow import normalize_code_text\n'
        '__all__: list[str] = ["normalize_code_text"]\n'
    )
    extended = ast.parse(
        "from docstruct.text.code_reflow import normalize_code_text\n"
        "__all__ = []\n__all__ += [\"normalize_code_text\"]\n"
    )

    assert _is_pure_docstruct_reexport(shim)
    assert _is_pure_docstruct_reexport(annotated)
    assert _is_pure_docstruct_reexport(extended)
    assert not _is_pure_docstruct_reexport(adapter)


@pytest.mark.parametrize("imports", [
    "import docstruct",
    "import docstruct.geometry",
    "import docstruct.geometry as geometry",
    "import docstruct.geometry, docstruct.placeholders as placeholders",
    "import docstruct.geometry as geometry\nfrom docstruct.placeholders import UNSTRUCTURED_PAGE_LABEL",
])
@pytest.mark.parametrize("docstring", ["", '\"\"\"Core migrated to docstruct.\"\"\"\n'])
def test_the_reexport_check_finds_module_imports(imports, docstring) -> None:
    assert _is_pure_docstruct_reexport(ast.parse(docstring + imports))


@pytest.mark.parametrize("source", [
    "import docstruct.geometry, os",
    "import docstruct.geometry\nfrom pathlib import Path",
    "import docstruct_extra",
    "from .docstruct import geometry",
    "from docstruct.geometry import is_bottom_left\ndef core_adapter():\n    return is_bottom_left(None, 1, 0)",
])
def test_the_reexport_check_keeps_adapters_and_other_imports(source) -> None:
    assert not _is_pure_docstruct_reexport(ast.parse(source))


def test_every_registered_bridge_is_an_adapter() -> None:
    """The re-export category is closed, so a registered bridge can only be an adapter."""
    assert set(BRIDGES.values()) == {ADAPTER}


@pytest.mark.parametrize("module", sorted(BRIDGES))
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


def test_the_builder_does_not_re_export_the_placeholder_label() -> None:
    """``UNSTRUCTURED_PAGE_LABEL`` lives in docstruct.placeholders (#191, step 3).

    The builder still uses it, under a private alias, to build the
    unstructured-page placeholder; it no longer exposes it as its own name.
    """
    import docstruct.placeholders
    from backend.core.manifest import builder

    assert not hasattr(builder, "UNSTRUCTURED_PAGE_LABEL")
    assert builder._UNSTRUCTURED_PAGE_LABEL is docstruct.placeholders.UNSTRUCTURED_PAGE_LABEL


def test_manifest_models_do_not_re_export_geometry() -> None:
    """Geometry callers import docstruct directly (#191, step 3)."""
    from backend.core.manifest import models

    assert not hasattr(models, "is_bottom_left")
