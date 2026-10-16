"""The SDK imports neither the core nor the Toolbox package.

It depends on the Toolbox only through its HTTP contract and receives its
configuration from the caller. Both packages are usually importable in the test
environment, so this test imports every module in a fresh interpreter that
refuses them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
FORBIDDEN = ("backend", "acessilia_toolbox")

_PROBE = f"""
import importlib, pkgutil, sys

FORBIDDEN = {FORBIDDEN!r}

class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in FORBIDDEN:
            raise ImportError(f"acessilia_sdk must not import {{name}}")
        return None

sys.meta_path.insert(0, _Block())
sys.path.insert(0, {str(SRC)!r})

import acessilia_sdk
failures = []
# Without onerror, walk_packages swallows a subpackage's ImportError and never
# lists the modules inside it.
for module in pkgutil.walk_packages(
    acessilia_sdk.__path__, "acessilia_sdk.", onerror=lambda name: failures.append(f"{{name}}: import failed")
):
    try:
        importlib.import_module(module.name)
    except ImportError as exc:
        failures.append(f"{{module.name}}: {{exc}}")
print("\\n".join(failures))
sys.exit(1 if failures else 0)
"""


def test_every_module_imports_without_core_or_toolbox() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_capability_registry_is_pure_data() -> None:
    """The contract checker loads this file by path, without the package."""
    import ast

    path = SRC / "acessilia_sdk" / "toolbox" / "capabilities.py"
    imported = {
        (node.module or "").split(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported <= {"__future__", "dataclasses", "typing"}, imported
