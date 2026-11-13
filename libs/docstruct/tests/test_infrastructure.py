"""docstruct does not touch infrastructure: network, environment, files, processes.

ADR-0017 states it as a rule: docstruct holds pure structural algorithms, so no
module may open a socket, read the environment or a file, write to the
process's streams, or start a subprocess. ``test_purity.py`` keeps docstruct on
the standard library, but the standard library has all of those, so it cannot
catch them (the review of #471 reproduced it with a module reading
``os.environ`` at import). Two checks do:

- statically, no module imports a standard library module whose job is
  infrastructure (``INFRASTRUCTURE_MODULES``), refers to a built-in that reads
  input, writes output, opens a file or runs code (``INFRASTRUCTURE_BUILTINS``,
  called or not), reaches the built-ins through ``builtins`` or
  ``__builtins__``, or reads a ``sys`` attribute that is the process's
  environment or streams (``SYS_ATTRIBUTES``);
- at import, in a fresh interpreter, opening a file, reading the environment,
  creating a socket, starting a process, calling those built-ins, printing or
  configuring logging from a docstruct module fails.

The static check also covers code that only runs when called. The import check
catches what the static one cannot see by name (``getattr`` on a module
object, aliases). A real need for one of these goes in ``ALLOWED`` with its
reason, so it stays visible.

**Scope.** The rule is ADR-0017's: network, environment, files and processes.
The clock (``time``, ``datetime``), randomness (``random``, ``secrets``,
``uuid``) and threads are not in it: they are about determinism, which would
be a rule of its own. docstruct uses none of them today.
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
    "ftplib": "network", "smtplib": "network", "poplib": "network",
    "imaplib": "network", "xmlrpc": "network", "socketserver": "network",
    "select": "network", "selectors": "network", "asyncio": "network",
    "webbrowser": "network",
    # environment
    "os": "environment", "platform": "environment", "getpass": "environment",
    "locale": "environment", "sysconfig": "environment", "site": "environment",
    # files
    "io": "files", "pathlib": "files", "shutil": "files", "tempfile": "files",
    "glob": "files", "fileinput": "files", "filecmp": "files",
    "linecache": "files", "zipfile": "files", "tarfile": "files", "gzip": "files",
    "bz2": "files", "lzma": "files", "sqlite3": "files", "dbm": "files",
    "shelve": "files", "mmap": "files", "importlib": "files", "pkgutil": "files",
    "logging": "files",
    # processes
    "subprocess": "processes", "multiprocessing": "processes",
    "concurrent": "processes", "pty": "processes", "signal": "processes",
    # the built-ins themselves, a way around INFRASTRUCTURE_BUILTINS
    "builtins": "code",
}
#: Built-ins that read input, write output, open a file or run code given as
#: data. Referring to one is refused, not only calling it (``f = eval``).
INFRASTRUCTURE_BUILTINS = {
    "open": "files", "print": "files", "input": "environment",
    "breakpoint": "environment", "exec": "code", "eval": "code",
    "compile": "code", "__import__": "code", "__builtins__": "code",
}
#: ``sys`` attributes that are the process's environment or streams.
SYS_ATTRIBUTES = {
    "argv": "environment", "orig_argv": "environment", "path": "environment",
    "executable": "environment", "exit": "processes",
    "stdin": "files", "stdout": "files", "stderr": "files",
    "__stdin__": "files", "__stdout__": "files", "__stderr__": "files",
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
            if node.module == "sys":
                uses.extend(
                    (node.lineno, f"sys.{alias.name}", SYS_ATTRIBUTES[alias.name])
                    for alias in node.names
                    if alias.name in SYS_ATTRIBUTES
                )
            names = [node.module]
        elif isinstance(node, ast.Name) and node.id in INFRASTRUCTURE_BUILTINS:
            uses.append((node.lineno, node.id, INFRASTRUCTURE_BUILTINS[node.id]))
            continue
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
            and node.attr in SYS_ATTRIBUTES
        ):
            uses.append((node.lineno, f"sys.{node.attr}", SYS_ATTRIBUTES[node.attr]))
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
        # The built-ins reached another way (review of #497).
        "import builtins\nvalue = builtins.eval('1 + 1')": ("builtins", "code"),
        "import builtins\nf = getattr(builtins, 'ev' + 'al')": ("builtins", "code"),
        "value = __builtins__['eval']('1')": ("__builtins__", "code"),
        "run = eval\nvalue = run('1')": ("eval", "code"),
        "answer = input()": ("input", "environment"),
        "breakpoint()": ("breakpoint", "environment"),
        "print('progress')": ("print", "files"),
        # sys and logging (review of #497).
        "import sys\nvalue = sys.argv": ("sys.argv", "environment"),
        "from sys import stdin": ("sys.stdin", "files"),
        "import sys\nsys.stdout.write('x')": ("sys.stdout", "files"),
        "import logging\nlogging.basicConfig(filename='x.log')": ("logging", "files"),
    }
    for source, (name, reach) in cases.items():
        assert any(use[1:] == (name, reach) for use in infrastructure_uses(source)), source
    assert infrastructure_uses("import re, json, math\nfrom collections import Counter") == []
    # sys is fine for what is not the process's environment or streams.
    assert infrastructure_uses("import sys\nlimit = sys.maxsize") == []
    # A method or attribute that shares a name is not the built-in.
    assert infrastructure_uses("import re\npattern = re.compile('a')\nitem.open = 1") == []
    # A relative import is docstruct's own, whatever its name.
    assert infrastructure_uses("from .io import read") == []


_PROBE = f"""
import builtins, logging, os, socket, subprocess, sys

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


# __import__ is not guarded here: every import statement calls it. The static
# check refuses explicit uses of it.
for _name in ("open", "print", "input", "breakpoint", "exec", "eval", "compile"):
    setattr(builtins, _name, _guard(_name, getattr(builtins, _name)))
os.getenv = _guard("os.getenv", os.getenv)
socket.socket = _guard("socket.socket", socket.socket)
subprocess.Popen = _guard("subprocess.Popen", subprocess.Popen)
logging.basicConfig = _guard("logging.basicConfig", logging.basicConfig)
logging.FileHandler = _guard("logging.FileHandler", logging.FileHandler)


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
sys.__stdout__.write("\\n".join(caught))
sys.exit(1 if caught else 0)
"""


def test_importing_every_module_touches_no_infrastructure() -> None:
    # No standard input and a timeout: an unguarded read must fail the test,
    # not hang it.
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        "infrastructure used at import:\n" + result.stdout + result.stderr
    )
