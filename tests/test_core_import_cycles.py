"""No import cycle among the core's modules (backend/core).

CodeQL found one between ``export/pandoc_exporter`` and
``export/renderers/html_renderer`` (code scanning #291, #292): the renderer
imported a msgid from the exporter, which imported the renderer inside a
function. It ran only because one side was lazy, so this scan counts imports
inside functions too, and ``from package import submodule`` as an import of
the submodule.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend" / "core"


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def import_graph(package: Path, root: Path) -> dict[str, set[str]]:
    """Each module of ``package`` -> the modules of ``package`` it imports, at any depth."""
    paths = {_module_name(path, root): path for path in package.rglob("*.py")}
    prefix = _module_name(package / "__init__.py", root)
    graph: dict[str, set[str]] = {}
    for name, path in paths.items():
        imported: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module)
                imported |= {f"{node.module}.{alias.name}" for alias in node.names}
        graph[name] = {
            module for module in imported
            if module in paths and module != name and module.startswith(prefix)
        }
    return graph


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Every cycle of ``graph``, each starting at its smallest module, sorted."""
    found: set[tuple[str, ...]] = set()

    def walk(node: str, stack: list[str]) -> None:
        for nxt in graph.get(node, ()):
            if nxt in stack:
                cycle = stack[stack.index(nxt):]
                start = cycle.index(min(cycle))
                found.add(tuple(cycle[start:] + cycle[:start]))
            elif nxt not in seen:
                seen.add(nxt)
                walk(nxt, [*stack, nxt])

    for module in graph:
        seen = {module}
        walk(module, [module])
    return [list(cycle) for cycle in sorted(found)]


def test_the_core_has_no_import_cycle() -> None:
    found = cycles(import_graph(CORE, ROOT))
    assert not found, "import cycles in backend/core:\n" + "\n".join(
        " -> ".join([*cycle, cycle[0]]) for cycle in found
    )


def test_the_scan_sees_a_lazy_cycle_through_a_package(tmp_path: Path) -> None:
    """A cycle like the one CodeQL found: one import is lazy, one goes through the package."""
    package = tmp_path / "pkg"
    (package / "sub").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "sub" / "__init__.py").write_text("")
    (package / "exporter.py").write_text(
        "TITLE = 'x'\n\ndef export():\n    from pkg.sub import renderer\n    return renderer\n"
    )
    (package / "sub" / "renderer.py").write_text("from pkg.exporter import TITLE\n")

    assert cycles(import_graph(package, tmp_path)) == [["pkg.exporter", "pkg.sub.renderer"]]
