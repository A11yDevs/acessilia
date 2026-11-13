"""The README's Public API table promises only what the modules export (ADR-0018).

Each module's ``__all__`` is the SDK's public API. The README table summarizes
it, in English and in Brazilian Portuguese. For every row:

- the module exists, and both READMEs list the same modules and names;
- a backticked word that is a name of the module is in its ``__all__``;
- any other backticked word is an attribute of a class the module exports (a
  method, a field), or a prose word listed in ``PROSE`` with its reason.

So a typo, or a name the module does not have, fails instead of passing as
prose.
"""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READMES = {"en": (ROOT / "README.md", "## Public API"), "pt-br": (ROOT / "README.pt-br.md", "## API pública")}
_ROW = re.compile(r"\| `(acessilia_sdk[\w.]*)` \| (.*) \|$")
#: Backticked words of a row that are neither module names nor class attributes.
PROSE = {
    ("acessilia_sdk.toolbox.config", "provider_key"): "an attribute of each client class, keying `providers`",
    ("acessilia_sdk.toolbox.config", "timeout_key"): "an attribute of each export client, keying `timeouts`",
    ("acessilia_sdk.toolbox.clients.adjudicate", "None"): "a return value",
    ("acessilia_sdk.toolbox.clients.adjudicate", "pB"): "a key of the adjudication answer",
    ("acessilia_sdk.toolbox.errors", "causes"): "an attribute ToolboxUnavailable sets on each instance",
}


def _table(language: str) -> dict[str, set[str]]:
    path, heading = READMES[language]
    text = path.read_text(encoding="utf-8")
    section = text[text.index(heading) :]
    section = section[: section.index("\n## ", 1)]
    rows = {}
    for line in section.splitlines():
        match = _ROW.match(line)
        if match:
            rows[match.group(1)] = set(re.findall(r"`(\w+)`", match.group(2)))
    return rows


def _class_attribute(module, name: str) -> bool:
    for exported in getattr(module, "__all__", ()):
        cls = getattr(module, exported, None)
        if inspect.isclass(cls) and (
            hasattr(cls, name)
            or name in getattr(cls, "__annotations__", {})
            or name in getattr(cls, "__dataclass_fields__", {})
        ):
            return True
    return False


def test_the_table_lists_modules() -> None:
    assert len(_table("en")) >= 10


def test_both_readmes_list_the_same_modules_and_names() -> None:
    assert _table("pt-br") == _table("en")


def test_every_listed_name_is_exported() -> None:
    problems = []
    for module_name, names in _table("en").items():
        module = importlib.import_module(module_name)
        exported = set(getattr(module, "__all__", ()))
        for name in sorted(names):
            if hasattr(module, name):
                if name not in exported:
                    problems.append(f"{module_name}.{name} is not exported")
            elif not _class_attribute(module, name) and (module_name, name) not in PROSE:
                problems.append(f"{module_name}.{name} is not a name of the module")
    assert not problems, f"README Public API table: {problems}"


def test_every_prose_word_is_still_in_the_table() -> None:
    table = _table("en")
    stale = [f"{module}.{name}" for module, name in PROSE if name not in table.get(module, set())]
    assert not stale, f"PROSE entries the README no longer uses: {stale}"
