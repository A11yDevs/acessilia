"""Compare a run with a reference, and the differences declared on purpose (#849).

Not part of the recorded harness (``runner.HARNESS_FILES``): changing how
outputs are compared does not change what a reference recorded.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from re import fullmatch
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
    The empty pointer ``""`` names the whole document; ``"/"`` names an
    empty property key, not the document root.
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
    return [] if _json_equal(reference, current) else [_item("changed", path, reference_path)]


def _json_equal(left: Any, right: Any) -> bool:
    """JSON equality: booleans differ from numbers, which compare exactly (#919)."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


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

    An optional non-empty string ``id`` additionally binds the declaration
    to the nearest enclosing member of a list with distinct string ids.
    Added/removed differences use the side containing them. Changed fields
    require the same identified member and list context on both sides.
    """
    for entry in declared:
        _validate_declaration(entry)
    found = differences(reference, current)
    unexplained = [item for item in found if not any(_explains(entry, item, reference, current) for entry in declared)]
    unused = [entry for entry in declared if not any(_explains(entry, item, reference, current) for item in found)]
    return unexplained, unused


def _validate_declaration(entry: Any) -> None:
    """Reject a malformed entry before computing or matching differences (#912)."""
    if not isinstance(entry, dict):
        raise ValueError(f"a declaration must be an object: {entry!r}")
    if entry.get("kind") not in ("added", "changed", "removed"):
        raise ValueError(f"a declaration's kind must be added, changed or removed: {entry!r}")
    if not isinstance(entry.get("path"), str):
        raise ValueError(f"a declaration's path must be a string: {entry!r}")
    if entry["kind"] in ("added", "changed") and "expected" not in entry:
        raise ValueError(f"a {entry['kind']} declaration must name its expected value: {entry!r}")
    if "id" in entry and (not isinstance(entry["id"], str) or not entry["id"]):
        raise ValueError(f"a declaration's id must be a non-empty string: {entry!r}")


def _explains(entry: dict[str, Any], item: dict[str, str], reference: Any, current: Any) -> bool:
    if entry["kind"] != item["kind"] or not fnmatchcase(item["path"], entry["path"]):
        return False
    if entry["kind"] == "removed":
        document = reference
        pointer = item.get("reference_path", item["path"])
        value_matches = "was" not in entry or _json_equal(resolve(document, pointer), entry["was"])
    else:
        document, pointer = current, item["path"]
        value_matches = _json_equal(resolve(document, pointer), entry["expected"])
    if not value_matches or "id" not in entry:
        return value_matches
    if item["kind"] == "changed":
        return _changed_id(reference, current, pointer, item.get("reference_path", pointer)) == entry["id"]
    return _enclosing_id(document, pointer) == entry["id"]


def _changed_id(reference: Any, current: Any, pointer: str, reference_pointer: str) -> str | None:
    """Trace the same list context through both paths, including moved ancestors.

    Plain arrays can stay positional, but a list advertising ids must be
    identified on both sides. Never fall back to an outer id through an
    ambiguous list, or pair equal inner ids under different parent members.
    """
    parts, old_parts = pointer.split("/")[1:], reference_pointer.split("/")[1:]
    if len(parts) != len(old_parts):
        return None
    owner = None
    for part, old_part in zip(parts, old_parts):
        child, old_child = resolve(current, f"/{part}"), resolve(reference, f"/{old_part}")
        if isinstance(current, list) and isinstance(reference, list):
            if _identified(current) and _identified(reference):
                if child["id"] != old_child["id"]:
                    return None
                owner = child["id"]
            elif part != old_part or _has_ids(current) or _has_ids(reference):
                return None
        elif part != old_part or isinstance(current, list) or isinstance(reference, list):
            return None
        current, reference = child, old_child
    return owner


def _has_ids(items: list[Any]) -> bool:
    return any(isinstance(item, dict) and "id" in item for item in items)


def _enclosing_id(document: Any, pointer: str) -> str | None:
    """The closest identified list member containing the difference (#895).

    Inspect ancestors, not descendants: changing a list's order cannot be
    attributed to an arbitrary member of that list. Reuse ``resolve`` so
    escaped property names and list indices follow the same rules as values.
    The caller supplies a valid, resolvable difference path.
    """
    parts = pointer.split("/")
    for size in range(len(parts) - 1, 0, -1):
        parent = resolve(document, "/".join(parts[:size]))
        if isinstance(parent, list) and _identified(parent):
            return resolve(parent, f"/{parts[size]}")["id"]
    return None


def resolve(document: Any, pointer: str) -> Any:
    """The value at ``pointer``; ``""`` names the document itself.

    ``"/"`` names an empty property key. Nonempty pointers start with ``/``;
    list indices are ``0`` or ASCII decimals without leading zeroes.
    An invalid prefix/index or a missing value raises ``KeyError(pointer)``.
    """
    if pointer and not pointer.startswith("/"):
        raise KeyError(pointer)
    value = document
    for segment in pointer.split("/")[1:]:
        segment = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not fullmatch(r"0|[1-9][0-9]*", segment):
                raise KeyError(pointer)
            try:
                index = int(segment)
            except ValueError:
                raise KeyError(pointer) from None
            if not 0 <= index < len(value):
                raise KeyError(pointer)
            value = value[index]
        elif isinstance(value, dict) and segment in value:
            value = value[segment]
        else:
            raise KeyError(pointer)
    return value



__all__ = ["differences", "explain", "resolve"]
