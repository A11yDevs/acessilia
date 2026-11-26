"""Compare a run with a reference, and the differences declared on purpose (#849).

Not part of the recorded harness (``runner.HARNESS_FILES``): changing how
outputs are compared does not change what a reference recorded.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from tests.differential.runner import escape


def differences(
    reference: Any, current: Any, path: str = "", reference_path: str | None = None
) -> list[dict[str, str]]:
    """Where ``current`` departs from ``reference``: each ``{kind, path}``,
    ``kind`` being ``added``, ``removed`` or ``changed`` and ``path`` a JSON
    pointer into ``current`` (into ``reference`` for ``removed``):
    ``/sections/0/blocks/2/alt_text``.

    A list of objects that all carry a distinct ``id`` (blocks, elements) is
    aligned by id, so a block inserted (a rescued paragraph) is one
    ``added``, not a change of every block after it; the same ids in
    another order are one ``changed`` of the list. Any other list is
    compared position by position. Where an aligned object moved, a
    difference inside it also names its ``reference_path``.
    """
    reference_path = path if reference_path is None else reference_path
    if isinstance(reference, dict) and isinstance(current, dict):
        found: list[dict[str, str]] = []
        for key in sorted(set(reference) | set(current)):
            child, reference_child = f"{path}/{escape(key)}", f"{reference_path}/{escape(key)}"
            if key not in reference:
                found.append({"kind": "added", "path": child})
            elif key not in current:
                found.append(_item("removed", reference_child, reference_child))
            else:
                found.extend(differences(reference[key], current[key], child, reference_child))
        return found
    if isinstance(reference, list) and isinstance(current, list):
        if _identified(reference) and _identified(current):
            return _aligned(reference, current, path, reference_path)
        found = []
        for index in range(max(len(reference), len(current))):
            child, reference_child = f"{path}/{index}", f"{reference_path}/{index}"
            if index >= len(reference):
                found.append({"kind": "added", "path": child})
            elif index >= len(current):
                found.append(_item("removed", reference_child, reference_child))
            else:
                found.extend(differences(reference[index], current[index], child, reference_child))
        return found
    return [] if reference == current else [_item("changed", path or "/", reference_path or "/")]


def _item(kind: str, path: str, reference_path: str) -> dict[str, str]:
    item = {"kind": kind, "path": path}
    if reference_path != path:
        item["reference_path"] = reference_path
    return item


def _identified(items: list[Any]) -> bool:
    """Whether ``items`` are objects that all carry a distinct, non-empty
    string ``id``; any other list (ids missing, repeated, empty or of
    another type, an empty list) is compared position by position."""
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    return (
        bool(items)
        and len(ids) == len(items)
        and all(isinstance(value, str) and value for value in ids)
        and len(set(ids)) == len(ids)
    )


def _aligned(reference: list[dict], current: list[dict], path: str, reference_path: str) -> list[dict[str, str]]:
    before = {item["id"]: index for index, item in enumerate(reference)}
    after = {item["id"]: index for index, item in enumerate(current)}
    found: list[dict[str, str]] = []
    if [key for key in before if key in after] != [key for key in after if key in before]:
        found.append(_item("changed", path, reference_path))
    for index, item in enumerate(current):
        if item["id"] not in before:
            found.append({"kind": "added", "path": f"{path}/{index}"})
        else:
            old = before[item["id"]]
            found.extend(differences(reference[old], item, f"{path}/{index}", f"{reference_path}/{old}"))
    found.extend(
        _item("removed", f"{reference_path}/{index}", f"{reference_path}/{index}")
        for index, item in enumerate(reference) if item["id"] not in after
    )
    return found


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
        return "was" not in entry or resolve(reference, item.get("reference_path", item["path"])) == entry["was"]
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
