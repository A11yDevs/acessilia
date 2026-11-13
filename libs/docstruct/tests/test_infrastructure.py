"""docstruct does not touch infrastructure: network, environment, files, processes.

ADR-0017 states it as a rule: docstruct holds pure structural algorithms, so no
module may open a socket, read the environment or a file, or start a
subprocess. ``test_purity.py`` keeps docstruct on the standard library, but the
standard library has all of those, so it cannot catch them (the review of #471
reproduced it with a module reading ``os.environ`` at import). Two checks do:

- statically, no module imports a standard library module whose job is
  infrastructure (``INFRASTRUCTURE_MODULES``) or calls a built-in that reads
  input, opens a file or runs code (``INFRASTRUCTURE_BUILTINS``);
- at import, in a fresh interpreter, opening a file, reading the environment,
  creating a socket or starting a process from a docstruct module fails.

The static check also covers code that only runs when called. The import check
catches what the static one cannot see by name (``getattr``, aliases). A real
need for one of these goes in ``ALLOWED`` with its reason, so it stays visible.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = SRC / "docstruct"

#: Standard library modules whose job is infrastructure, by what they reach.
INFRASTRUCTURE_MODULES = {
    # network
    "socket": "network", "ssl": "network", "http": "network", "urllib": "network",
    "ftplib": "network", "smtplib": "network", "poplib": "network", "imaplib": "network",
    "xmlrpc": "network", "socketserver": "network", "select": "network",
    "selectors": "network", "asyncio": "network", "webbrowser": "network",
    # environment
    "os": "environment", "platform": "environment", "getpass": "environment",
    "locale": "environment", "sysconfig": "environment", "site": "environment",
    # files
    "io": "files", "pathlib": "files", "shutil": "files", "tempfile": "files",
    "glob": "files", "fileinput": "files", "filecmp": "files", "linecache": "files",
    "zipfile": "files", "tarfile": "files", "gzip": "files", "bz2": "files",
    "lzma": "files", "sqlite3": "files", "dbm": "files", "shelve": "files",
    "mmap": "files", "importlib": "files", "pkgutil": "files",
    # processes
    "subprocess": "processes", "multiprocessing": "processes", "concurrent": "processes",
    "pty": "processes", "signal": "processes",
}
#: Built-ins that read input, open a file or run code given as data.
INFRASTRUCTURE_BUILTINS = {
    "open": "files", "input": "environment", "breakpoint": "environment",
    "exec": "code", "eval": "code", "compile": "code", "__import__": "code",
}
#: ``"module.py:name": "reason"`` for a reviewed exception. Empty: none is needed.
ALLOWED: dict[str, str] = {}


def infrastructure_uses(source: str) -> list[tuple[int, str, str]]:
    """``(line, name, what it reaches)`` for every infrastructure use in ``source``."""
    uses = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in INFRASTRUCTURE_BUILTINS:
                uses.append((node.lineno, node.func.id, INFRASTRUCTURE_BUILTINS[node.func.id]))
            continue
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top in INFRASTRUCTURE_MODULES:
                uses.append((node.lineno, name, INFRASTRUCTURE_MODULES[top]))
    return uses


def test_no_module_uses_infrastructure() -> None:
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE).as_posix()
        for line, name, reach in infrastructure_uses(path.read_text(encoding="utf-8")):
            if f"{relative}:{name}" not in ALLOWED:
                offenders.append(f"docstruct/{relative}:{line}: {name} ({reach})")
    assert not offenders, (
        "docstruct must not touch the network, the environment, files or processes "
        f"(ADR-0017); add a reviewed exception to ALLOWED if one is needed: {offenders}"
    )


def test_every_exception_is_still_needed() -> None:
    used = {
        f"{path.relative_to(PACKAGE).as_posix()}:{name}"
        for path in PACKAGE.rglob("*.py")
        for _, name, _ in infrastructure_uses(path.read_text(encoding="utf-8"))
    }
    assert set(ALLOWED) <= used, f"exceptions nothing uses any more: {sorted(set(ALLOWED) - used)}"


def test_the_static_check_recognizes_each_kind_of_use() -> None:
    """The checker itself: a broken one would report no use at all."""
    cases = {
        "import os\nvalue = os.environ['HOME']": ("os", "environment"),
        "from pathlib import Path\nPath('x').read_text()": ("pathlib", "files"),
        "import urllib.request": ("urllib.request", "network"),
        "from subprocess import run": ("subprocess", "processes"),
        "data = open('table.json').read()": ("open", "files"),
        "module = __import__('socket')": ("__import__", "code"),
        "def later():\n    import socket\n    return socket.socket()": ("socket", "network"),
    }
    for source, (name, reach) in cases.items():
        assert any(use[1:] == (name, reach) for use in infrastructure_uses(source)), source
    assert infrastructure_uses("import re, json, math\nfrom collections import Counter") == []
    # A relative import is docstruct's own, whatever its name.
    assert infrastructure_uses("from .io import read") == []


_PROBE = f"""
import builtins, os, socket, subprocess, sys

PACKAGE = {str(PACKAGE)!r}
caught = []


def _from_docstruct(depth=2):
    frame = sys._getframe(depth)
    return frame.f_code.co_filename.startswith(PACKAGE)


def _guard(name, original):
    def guarded(*args, **kwargs):
        if _from_docstruct():
            caught.append(f"{{name}} from {{sys._getframe(1).f_code.co_filename}}")
            raise PermissionError(f"docstruct must not use {{name}}")
        return original(*args, **kwargs)
    return guarded


builtins.open = _guard("open", builtins.open)
os.getenv = _guard("os.getenv", os.getenv)
socket.socket = _guard("socket.socket", socket.socket)
subprocess.Popen = _guard("subprocess.Popen", subprocess.Popen)


def _environ_guard(name):
    def guarded(self, *args, **kwargs):
        if _from_docstruct():
            caught.append(f"os.environ.{{name}} from {{sys._getframe(1).f_code.co_filename}}")
            raise PermissionError("docstruct must not read the environment")
        return getattr(super(_Environ, self), name)(*args, **kwargs)
    return guarded


class _Environ(type(os.environ)):
    # Each reading method checks its own caller: ``get`` reaches ``__getitem__``
    # through ``Mapping``, whose frame is not docstruct's.
    __getitem__ = _environ_guard("__getitem__")
    get = _environ_guard("get")
    __contains__ = _environ_guard("__contains__")
    __iter__ = _environ_guard("__iter__")
    keys = _environ_guard("keys")
    items = _environ_guard("items")
    values = _environ_guard("values")
    copy = _environ_guard("copy")


os.environ.__class__ = _Environ

sys.path.insert(0, {str(SRC)!r})
import importlib, pkgutil
import docstruct

for module in pkgutil.walk_packages(docstruct.__path__, "docstruct."):
    try:
        importlib.import_module(module.name)
    except PermissionError:
        pass
print("\\n".join(caught))
sys.exit(1 if caught else 0)
"""


def test_importing_every_module_touches_no_infrastructure() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, (
        "infrastructure used at import:\n" + result.stdout + result.stderr
    )
