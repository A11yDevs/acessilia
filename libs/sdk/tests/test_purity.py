"""The SDK imports neither the core nor the Toolbox package.

It depends on the Toolbox only through its HTTP contract and receives its
configuration from the caller. Both packages are usually importable in the test
environment, so this test imports every module in a fresh interpreter that
refuses them.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
#: The only runtime dependencies the SDK may have (ADR-0002, P2): the HTTP
#: client, and docstruct for shared pure algorithms.
ALLOWED_DEPENDENCIES = {"httpx": "httpx", "acessilia-docstruct": "docstruct"}
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


def test_runtime_dependencies_stay_within_httpx_and_docstruct() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {
        re.split(r"[\s<>=!~;\[@]", requirement, maxsplit=1)[0].lower()
        for requirement in project.get("dependencies", [])
    }
    assert declared <= set(ALLOWED_DEPENDENCIES), declared - set(ALLOWED_DEPENDENCIES)


def test_imports_stay_within_the_standard_library_httpx_and_docstruct() -> None:
    allowed = set(sys.stdlib_module_names) | set(ALLOWED_DEPENDENCIES.values()) | {
        "acessilia_sdk"
    }
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            else:
                continue
            offenders += [
                f"{path.relative_to(SRC)}:{node.lineno}: {name}"
                for name in names
                if name.split(".")[0] not in allowed
            ]
    assert not offenders, offenders
