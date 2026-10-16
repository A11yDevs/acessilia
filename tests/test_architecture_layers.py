"""Dependency direction between the Acessilia layers.

docstruct (pure algorithms) → Toolbox (remote capabilities) → client → core.
The core reaches the Toolbox through its published HTTP contract only, so the
backend must never import the Toolbox package; docstruct guards its own side in
``libs/docstruct/tests/test_purity.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
FORBIDDEN_IN_BACKEND = ("acessilia_toolbox",)


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    return roots


def test_backend_does_not_import_the_toolbox_package() -> None:
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in BACKEND_DIR.rglob("*.py")
        if _imported_roots(path) & set(FORBIDDEN_IN_BACKEND)
    )
    assert not offenders, (
        "backend modules importing the Toolbox package "
        f"(use the HTTP contract instead): {offenders}"
    )
