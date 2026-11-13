"""The core uses only the SDK's public API: what each SDK module lists in ``__all__``.

ADR-0018. The SDK is a public, versioned API (ADR-0017): the core is one of its
callers, not a privileged one. So everything the core, its scripts and its
tests take from ``acessilia_sdk`` must be a name the module exports in
``__all__``, or a public SDK module itself:

- ``from acessilia_sdk.x import name`` and ``import acessilia_sdk.x``;
- ``module.name`` read through an imported SDK module;
- ``getattr``, ``setattr``, ``hasattr`` and ``delattr`` on an SDK module, and
  ``monkeypatch.setattr``, ``monkeypatch.delattr`` and ``patch.object`` with
  one, when the name is a literal string (a name computed at runtime cannot be
  checked statically);
- dotted string paths, such as a ``monkeypatch.setattr`` target, judged by the
  first segment after the module (``Client.method`` is judged by ``Client``).

A reviewed need for an internal name goes in ``ALLOWED`` with its reason, so it
stays visible; an entry nothing uses any more fails the second test.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import acessilia_sdk

ROOT = Path(__file__).resolve().parents[1]
#: The core's code, its scripts and its tests.
SCANNED = ("backend", "scripts", "tests")
#: ``"acessilia_sdk.module.name": "reason"`` for a reviewed exception. Empty.
ALLOWED: dict[str, str] = {}
#: Calls that read or replace ``getattr(module, "name")``-style attributes.
_NAME_FUNCTIONS = frozenset({"getattr", "setattr", "hasattr", "delattr"})
_NAME_METHODS = frozenset({"setattr", "delattr", "object"})
_STRING_PATH = re.compile(r"""["'](acessilia_sdk(?:\.\w+)+)["']""")


def _sdk_modules() -> dict[str, frozenset[str]]:
    """Every SDK module, with its ``__all__`` (empty when it has none)."""
    modules = {"acessilia_sdk": frozenset(getattr(acessilia_sdk, "__all__", ()))}
    for info in pkgutil.walk_packages(acessilia_sdk.__path__, "acessilia_sdk."):
        module = importlib.import_module(info.name)
        modules[info.name] = frozenset(getattr(module, "__all__", ()))
    return modules


MODULES = _sdk_modules()


def is_public(path: str) -> bool:
    """Whether ``acessilia_sdk.…`` names a public module or a name a module exports."""
    if path in MODULES:
        return not any(part.startswith("_") for part in path.split("."))
    parts = path.split(".")
    # The longest module prefix decides: the next segment must be in its __all__.
    for cut in range(len(parts) - 1, 0, -1):
        module = ".".join(parts[:cut])
        if module in MODULES:
            return is_public(module) and parts[cut] in MODULES[module]
    return False


def sdk_uses(source: str) -> list[tuple[int, str]]:
    """``(line, dotted path)`` for every SDK name ``source`` imports, reads or names."""
    tree = ast.parse(source)
    uses: list[tuple[int, str]] = []
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "acessilia_sdk":
                    uses.append((node.lineno, alias.name))
                    aliases[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else "acessilia_sdk"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if node.module.split(".")[0] != "acessilia_sdk":
                continue
            for alias in node.names:
                path = f"{node.module}.{alias.name}"
                uses.append((node.lineno, path))
                if path in MODULES:
                    aliases[alias.asname or alias.name] = path
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain = []
            current: ast.expr = node
            while isinstance(current, ast.Attribute):
                chain.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name) and current.id in aliases:
                path = ".".join([aliases[current.id], *reversed(chain)])
                # Only the outermost attribute of a chain is recorded.
                uses.append((node.lineno, path))
        if isinstance(node, ast.Call) and len(node.args) >= 2:
            function = node.func
            named = (isinstance(function, ast.Name) and function.id in _NAME_FUNCTIONS) or (
                isinstance(function, ast.Attribute) and function.attr in _NAME_METHODS
            )
            target, name = node.args[0], node.args[1]
            if (
                named
                and isinstance(target, ast.Name)
                and target.id in aliases
                and isinstance(name, ast.Constant)
                and isinstance(name.value, str)
            ):
                uses.append((node.lineno, f"{aliases[target.id]}.{name.value}"))
    for match in _STRING_PATH.finditer(source):
        uses.append((source[: match.start()].count("\n") + 1, match.group(1)))
    return uses


def _scanned_files() -> list[Path]:
    return sorted(
        path
        for root in SCANNED
        for path in (ROOT / root).rglob("*.py")
        if path.resolve() != Path(__file__).resolve()
    )


def test_the_core_uses_only_the_sdk_public_api() -> None:
    offenders = []
    for path in _scanned_files():
        for line, used in sdk_uses(path.read_text(encoding="utf-8")):
            if not is_public(used) and used not in ALLOWED:
                offenders.append(f"{path.relative_to(ROOT)}:{line}: {used}")
    assert not offenders, (
        "Names outside the SDK's __all__ (ADR-0018). Export them from the SDK, "
        f"or add a reviewed exception to ALLOWED: {sorted(set(offenders))}"
    )


def test_every_exception_is_still_needed() -> None:
    used = {
        name
        for path in _scanned_files()
        for _, name in sdk_uses(path.read_text(encoding="utf-8"))
    }
    assert set(ALLOWED) <= used, f"exceptions nothing uses any more: {sorted(set(ALLOWED) - used)}"


def test_every_sdk_module_declares_its_public_names() -> None:
    """Without ``__all__``, a module would have no public name at all.

    ``__all__ = []`` is a valid declaration (no public name). The package
    itself (``__version__``), entry points such as ``acessilia_sdk.__main__``
    and private modules (a segment starting with ``_``) are not API modules.
    """
    undeclared = sorted(
        name
        for name in MODULES
        if name != "acessilia_sdk"
        and not any(part.startswith("_") for part in name.split("."))
        and not hasattr(importlib.import_module(name), "__all__")
    )
    assert not undeclared, f"SDK modules without __all__: {undeclared}"


def test_the_guard_recognizes_each_kind_of_use() -> None:
    """The guard itself: a broken one would report every use as public."""
    module, exported = "acessilia_sdk.toolbox.artifacts", "download_artifact"
    namespace = vars(importlib.import_module(module))
    # A function or class the module defines but does not export.
    internal = next(
        name
        for name, value in namespace.items()
        if name not in MODULES[module]
        and getattr(value, "__module__", None) == module
        and callable(value)
    )
    cases = {
        f"from {module} import {internal}": f"{module}.{internal}",
        f"from acessilia_sdk.toolbox import artifacts\nartifacts.{internal}()": f"{module}.{internal}",
        f"import {module} as t\nt.{internal}": f"{module}.{internal}",
        f"monkeypatch.setattr('{module}.{internal}', fake)": f"{module}.{internal}",
        # Literal names through a module object (review of #501).
        f"from acessilia_sdk.toolbox import artifacts\ngetattr(artifacts, '{internal}')": f"{module}.{internal}",
        f"from acessilia_sdk.toolbox import artifacts\nmonkeypatch.setattr(artifacts, '{internal}', fake)": f"{module}.{internal}",
        f"from acessilia_sdk.toolbox import artifacts\npatch.object(artifacts, '{internal}')": f"{module}.{internal}",
        f"import {module} as a\nhasattr(a, '{internal}')": f"{module}.{internal}",
    }
    for source, path in cases.items():
        assert path in {used for _, used in sdk_uses(source)}, source
        assert not is_public(path), path
    for public in (
        f"{module}.{exported}",
        module,
        "acessilia_sdk.toolbox.clients.pdf.ToolboxPdfClient.render",
        "acessilia_sdk.toolbox.ToolboxError",
    ):
        assert is_public(public), public
    assert not is_public("acessilia_sdk.toolbox.clients.pdf.NotAName")
