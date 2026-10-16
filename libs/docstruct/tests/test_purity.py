"""The library imports nothing from the applications that use it.

docstruct sits below both the core (``backend``) and the Toolbox
(``acessilia_toolbox``) and must stay installable on its own. Those packages
are usually importable in the test environment, so a stray import would go
unnoticed; this test imports every module in a fresh interpreter that refuses
them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
FORBIDDEN = ("backend", "acessilia_toolbox", "acessilia_sdk")

_PROBE = f"""
import importlib, pkgutil, sys

FORBIDDEN = {FORBIDDEN!r}

class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in FORBIDDEN:
            raise ImportError(f"docstruct must not import {{name}}")
        return None

sys.meta_path.insert(0, _Block())
sys.path.insert(0, {str(SRC)!r})

import docstruct
failures = []
for module in pkgutil.walk_packages(docstruct.__path__, "docstruct."):
    try:
        importlib.import_module(module.name)
    except ImportError as exc:
        failures.append(f"{{module.name}}: {{exc}}")
print("\\n".join(failures))
sys.exit(1 if failures else 0)
"""


def test_every_module_imports_without_the_applications() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
