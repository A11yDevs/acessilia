"""Compare a run with a reference, and the differences declared on purpose (#849).

Not part of the recorded harness (``runner.HARNESS_FILES``): changing how
outputs are compared does not change what a reference recorded.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from tests.differential.runner import escape


def differences(reference: Any, current: Any, path: str = "") -> list[dict[str, str]]:
    """Where ``current`` departs from ``reference``: each ``{kind, path}``,
    ``kind`` being ``added``, ``removed`` or ``changed`` and ``path`` a JSON
    pointer (``/sections/0/blocks/2/alt_text``)."""
    if isinstance(reference, dict) and isinstance(current, dict):
        found: list[dict[str, str]] = []
        for key in sorted(set(reference) | set(current)):
            child = f"{path}/{escape(key)}"
            if key not in reference:
                found.append({"kind": "added", "path": child})
            elif key not in current:
                found.append({"kind": "removed", "path": child})
            else:
                found.extend(differences(reference[key], current[key], child))
        return found
    if isinstance(reference, list) and isinstance(current, list):
        found = []
        for index in range(max(len(reference), len(current))):
            child = f"{path}/{index}"
            if index >= len(reference):
                found.append({"kind": "added", "path": child})
            elif index >= len(current):
                found.append({"kind": "removed", "path": child})
            else:
                found.extend(differences(reference[index], current[index], child))
        return found
    return [] if reference == current else [{"kind": "changed", "path": path or "/"}]


def explain(
    reference: Any, current: Any, declared: list[dict[str, Any]]
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """The differences between ``reference`` and ``current`` that no entry of
    ``declared`` explains, and the entries that explain none of them.

    An entry is ``{kind, path, reason}``, ``path`` a JSON pointer in which
    ``*`` matches any run of characters, plus the value it allows: an
    ``added`` or ``changed`` entry names the value now (``expected``), so a
    later change of the same field is not accepted with it; a ``removed``
    entry may name the value that was (``was``).
    """
    found = differences(reference, current)
    unexplained = [item for item in found if not any(_explains(entry, item, reference, current) for entry in declared)]
    unused = [entry for entry in declared if not any(_explains(entry, item, reference, current) for item in found)]
    return unexplained, unused


def _explains(entry: dict[str, Any], item: dict[str, str], reference: Any, current: Any) -> bool:
    if entry["kind"] != item["kind"] or not fnmatchcase(item["path"], entry["path"]):
        return False
    if entry["kind"] == "removed":
        return "was" not in entry or resolve(reference, item["path"]) == entry["was"]
    if "expected" not in entry:
        raise ValueError(f"an {entry['kind']} difference must name its expected value: {entry}")
    return resolve(current, item["path"]) == entry["expected"]


def resolve(document: Any, pointer: str) -> Any:
    """The value at ``pointer``; ``KeyError`` when there is none."""
    value = document
    for segment in pointer.split("/")[1:]:
        segment = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            index = int(segment)
            if not 0 <= index < len(value):
                raise KeyError(pointer)
            value = value[index]
        elif isinstance(value, dict) and segment in value:
            value = value[segment]
        else:
            raise KeyError(pointer)
    return value



__all__ = ["differences", "explain", "resolve"]
