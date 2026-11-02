"""List blocks.

Pure: zero external dependencies, standard library only.

A ``list`` block holds its ``items`` as text; an ordered one may carry
``start``, the number of its first item, when the source list was split
by a formula or a paragraph between its items, and ``numbering``, the
style of its markers when they are not decimal ("a)", "ii.").
"""
from __future__ import annotations

import re
from typing import Any

NUMBERING_STYLES = ("decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman")

_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
_MARKER = re.compile(r"^\(?([0-9]+|[a-z]+)[.)]?$", re.IGNORECASE)


def list_start(block: dict[str, Any]) -> int:
    """The number of an ordered list block's first item: ``start``, else 1."""
    start = block.get("start")
    return start if isinstance(start, int) and not isinstance(start, bool) and start > 0 else 1


def list_numbering(block: dict[str, Any]) -> str:
    """The marker style of an ordered list block: ``numbering``, else decimal."""
    numbering = block.get("numbering")
    return numbering if numbering in NUMBERING_STYLES else "decimal"


def marker_numbering(marker: Any) -> tuple[int, str] | None:
    """The number and style an ordered item's marker gives, or None for a bullet.

    "3." is 3, decimal; "b)" is 2, lower-alpha; "IV." is 4, upper-roman. A
    lone letter is a letter, except "i"/"I", which opens a roman list far
    more often than it is the ninth letter.
    """
    match = _MARKER.match(str(marker or "").strip())
    if match is None:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token), "decimal"
    case = "upper" if token.isupper() else "lower"
    lower = token.lower()
    if lower == "i" or (len(lower) > 1 and set(lower) <= set(_ROMAN_VALUES)):
        value = _roman_value(lower)
        return (value, f"{case}-roman") if value else None
    if len(lower) == 1:
        return ord(lower) - ord("a") + 1, f"{case}-alpha"
    return None


def item_label(number: int, numbering: str) -> str:
    """The marker text of item ``number`` in ``numbering`` style, without its period."""
    if numbering.endswith("-alpha"):
        label = ""
        while number > 0:
            number, rest = divmod(number - 1, 26)
            label = chr(ord("a") + rest) + label
    elif numbering.endswith("-roman"):
        label = _roman_label(number)
    else:
        return str(number)
    return label.upper() if numbering.startswith("upper") else label


def _roman_value(token: str) -> int:
    total = 0
    for index, char in enumerate(token):
        value = _ROMAN_VALUES[char]
        following = _ROMAN_VALUES[token[index + 1]] if index + 1 < len(token) else 0
        total += -value if value < following else value
    return total if total > 0 and _roman_label(total) == token else 0


def _roman_label(number: int) -> str:
    label = ""
    for value, symbol in (
        (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
        (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    ):
        while number >= value:
            label += symbol
            number -= value
    return label


__all__ = ["NUMBERING_STYLES", "item_label", "list_numbering", "list_start", "marker_numbering"]
