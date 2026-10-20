"""docstruct depends on nothing outside the Python standard library.

It sits below the core (``backend``), the SDK and the Toolbox
(``acessilia_toolbox``) and must stay installable on its own (ADR-0002). Those
packages, and other libraries, are usually importable in the test environment,
so a stray import would go unnoticed. Three checks keep it pure:

- ``pyproject.toml`` declares no runtime dependency;
- every import outside the standard library is an optional accelerator listed
  in ``OPTIONAL_ACCELERATORS`` and guarded by ``except ImportError``;
- every module imports in a fresh interpreter that refuses everything outside
  the standard library, so the guarded fallbacks really work.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
#: Optional speed-ups with a pure-Python fallback; never required.
OPTIONAL_ACCELERATORS = frozenset({"rapidfuzz"})

_PROBE = f"""
import importlib, pkgutil, sys

ALLOWED = set(sys.stdlib_module_names) | {{"docstruct"}}

class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in ALLOWED:
            raise ImportError(f"docstruct must not import {{name}}")
        return None

sys.meta_path.insert(0, _Block())
sys.path.insert(0, {str(SRC)!r})

import docstruct
failures = []
# Without onerror, walk_packages swallows a subpackage's ImportError and never
# lists the modules inside it.
for module in pkgutil.walk_packages(
    docstruct.__path__, "docstruct.", onerror=lambda name: failures.append(f"{{name}}: import failed")
):
    try:
        importlib.import_module(module.name)
    except ImportError as exc:
        failures.append(f"{{module.name}}: {{exc}}")
print("\\n".join(failures))
sys.exit(1 if failures else 0)
"""


def test_every_module_imports_with_the_standard_library_only() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_runtime_dependency_is_declared() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project.get("dependencies", []) == []


def _guarded_by_import_error(handlers: list[ast.ExceptHandler]) -> bool:
    caught = set()
    for handler in handlers:
        names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        caught |= {name.id for name in names if isinstance(name, ast.Name)}
    return bool(caught & {"ImportError", "ModuleNotFoundError"})


def test_imports_outside_the_standard_library_are_guarded_accelerators() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded = {
            id(node)
            for block in ast.walk(tree)
            if isinstance(block, ast.Try) and _guarded_by_import_error(block.handlers)
            for statement in block.body
            for node in ast.walk(statement)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top == "docstruct":
                    continue
                if top in OPTIONAL_ACCELERATORS and id(node) in guarded:
                    continue
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {name}")
    assert not offenders, (
        "docstruct imports outside the standard library (only guarded optional "
        f"accelerators are allowed): {offenders}"
    )
