"""The README's Public API table promises only what the modules export (ADR-0018).

Each module's ``__all__`` is the SDK's public API. The README table summarizes
it: every module it lists exists, and every name it shows in backticks that is
a name of that module is in the module's ``__all__``. Backticked words that are
not module names (a method, a field, a key) are left to the prose.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"
_ROW = re.compile(r"\| `(acessilia_sdk[\w.]*)` \| (.*) \|$")


def _table() -> dict[str, set[str]]:
    text = README.read_text(encoding="utf-8")
    section = text[text.index("## Public API") :]
    section = section[: section.index("\n## ", 1)]
    rows = {}
    for line in section.splitlines():
        match = _ROW.match(line)
        if match:
            rows[match.group(1)] = set(re.findall(r"`(\w+)`", match.group(2)))
    return rows


def test_the_table_lists_modules() -> None:
    assert len(_table()) >= 10


def test_every_listed_name_is_exported() -> None:
    unexported = []
    for module_name, names in _table().items():
        module = importlib.import_module(module_name)
        exported = set(getattr(module, "__all__", ()))
        unexported += [
            f"{module_name}.{name}"
            for name in sorted(names)
            if hasattr(module, name) and name not in exported
        ]
    assert not unexported, f"README lists names the module does not export: {unexported}"
