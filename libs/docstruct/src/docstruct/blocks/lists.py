"""List blocks.

Pure: zero external dependencies, standard library only.

A ``list`` block holds its ``items`` as text; an ordered one may carry
``start``, the number of its first item, when the source list was split
by a formula or a paragraph between its items, and ``numbering``, the
style of its markers when they are not decimal ("a)", "ii.").
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

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


class ListSourceElement(Protocol):
    """What :func:`recover_empty_lettered_list_items` reads of an element.

    ``docstruct.manifest.DocumentElement`` has these attributes, and so does
    the core's manifest element; neither needs converting. They are read-only
    properties: a writable protocol attribute is invariant, so ``type: str``
    would reject an element whose ``type`` is a ``Literal`` of kinds, and
    ``metadata: Mapping`` one whose ``metadata`` is a ``dict``.
    """

    @property
    def id(self) -> str: ...

    @property
    def type(self) -> str: ...

    @property
    def text(self) -> str | None: ...

    @property
    def parent_id(self) -> str | None: ...

    @property
    def reading_order(self) -> int: ...

    @property
    def metadata(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class LetteredListRecovery:
    """What :func:`recover_empty_lettered_list_items` found; empty when nothing."""

    #: Empty item id -> (its recovered text, its marker, e.g. "a)").
    items: dict[str, tuple[str, str]]
    #: Source paragraph id -> the text it keeps (its prefix), possibly "".
    consumed: dict[str, str]
    #: First item id -> (source paragraph id, preamble to emit before the item).
    preambles: dict[str, tuple[str, str]]


#: ``a)`` at the start of the text or after whitespace: a letter after any
#: other character (``(a)``, ``x(a)``) is an enumeration inside prose.
LETTERED_LIST_SOURCE_MARKER = re.compile(
    r"(?:^|(?<=\s))(?P<marker>[A-Za-z])\)(?=\s)"
)


def recover_empty_lettered_list_items(
    elements: Sequence[ListSourceElement],
) -> LetteredListRecovery:
    """Recover a fully extracted lettered list from a sibling text element.

    Some extractors emit empty ``list_item`` elements while leaving the actual
    ``a) ... b) ... c)`` text in a paragraph on the same page. Move that text
    only when one paragraph in the same heading section has the exact marker
    sequence of one fully empty list group. Explicit non-alphabetic markers,
    ambiguous matches and partial matches stay untouched.

    Returns a :class:`LetteredListRecovery`: item id -> (text, marker),
    source paragraph id -> remaining prefix, and first item id -> (source
    paragraph id, preamble text) to emit before that item. The paragraph's
    list text is consumed once, avoiding duplicate output. A preamble after
    the first item moves before it, keeping the exercise's introduction ahead
    of its questions. The elements are read, never changed.

    The last item runs to the end of the paragraph: a sentence after it (a
    closing remark) stays in that item, since a question can itself span
    several sentences and no marker says where it ends.
    """
    sections: dict[str, int] = {}
    section = 0
    groups: dict[str, list[ListSourceElement]] = {}
    for element in elements:
        if element.type in {"title", "heading"}:
            section += 1
        sections[element.id] = section
        if element.type == "list_item" and element.parent_id:
            groups.setdefault(element.parent_id, []).append(element)

    empty_groups = {
        parent_id: sorted(items, key=lambda item: item.reading_order)
        for parent_id, items in groups.items()
        if len(items) >= 2
        and all(not (item.text or "").strip() for item in items)
        and len({sections[item.id] for item in items}) == 1
    }
    if not empty_groups:
        return LetteredListRecovery({}, {}, {})

    sources = [
        element
        for element in elements
        if element.type in {"paragraph", "unknown"} and (element.text or "").strip()
    ]
    matches_by_group: dict[
        str, list[tuple[ListSourceElement, list[tuple[str, str]], str]]
    ] = {parent_id: [] for parent_id in empty_groups}

    for parent_id, items in empty_groups.items():
        known_markers: list[tuple[int, str] | None] = []
        for item in items:
            marker = str(item.metadata.get("marker") or "").strip()
            parsed = marker_numbering(marker) if marker else None
            if marker and (parsed is None or not parsed[1].endswith("-alpha")):
                known_markers = []
                break
            known_markers.append(parsed)
        if not known_markers:
            continue

        for source in sources:
            if sections[source.id] != sections[items[0].id]:
                continue
            source_text = source.text or ""
            markers = list(LETTERED_LIST_SOURCE_MARKER.finditer(source_text))
            if len(markers) != len(items):
                continue
            parsed_markers = [
                marker_numbering(f"{match.group('marker')})") for match in markers
            ]
            if any(
                marker is None or not marker[1].endswith("-alpha")
                for marker in parsed_markers
            ):
                continue
            typed_markers = [marker for marker in parsed_markers if marker is not None]
            style = typed_markers[0][1]
            first_number = typed_markers[0][0]
            if any(marker[1] != style for marker in typed_markers) or [
                marker[0] for marker in typed_markers
            ] != list(range(first_number, first_number + len(items))):
                continue
            if any(
                known is not None and known != actual
                for known, actual in zip(known_markers, typed_markers, strict=True)
            ):
                continue

            item_texts = []
            for index, match in enumerate(markers):
                end = markers[index + 1].start() if index + 1 < len(markers) else len(source_text)
                item_texts.append(source_text[match.end() : end].strip())
            if not all(item_texts):
                continue
            prefix = source_text[: markers[0].start()].strip()
            marker_texts = [match.group("marker") + ")" for match in markers]
            matches_by_group[parent_id].append(
                (source, list(zip(marker_texts, item_texts, strict=True)), prefix)
            )

    group_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for parent_id, matches in matches_by_group.items():
        group_counts[parent_id] = len(matches)
        for source, _, _ in matches:
            source_counts[source.id] = source_counts.get(source.id, 0) + 1

    recovered: dict[str, tuple[str, str]] = {}
    consumed: dict[str, str] = {}
    preambles: dict[str, tuple[str, str]] = {}
    positions = {element.id: index for index, element in enumerate(elements)}
    for parent_id, matches in matches_by_group.items():
        if group_counts[parent_id] != 1:
            continue
        source, marked_texts, prefix = matches[0]
        if source_counts[source.id] != 1:
            continue
        for item, (marker, text) in zip(
            empty_groups[parent_id], marked_texts, strict=True
        ):
            recovered[item.id] = (text, marker)
        first_item = empty_groups[parent_id][0]
        if prefix and positions[source.id] > positions[first_item.id]:
            preambles[first_item.id] = (source.id, prefix)
            prefix = ""
        consumed[source.id] = prefix

    return LetteredListRecovery(recovered, consumed, preambles)


def merge_list_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blocks with each run of items from one source list joined into one list.

    Each list item becomes a list block of its own. Consecutive ones that share
    their Docling list (``parent_id``) and kind are one list; an item kept
    apart by a formula or a paragraph stays a list of its own, whose ``start``
    carries the numbering on.

    The joined list keeps the first item's identity and provenance (``id``,
    ``manifest_element_id``, ``source_location``); the later items lend it
    their text only. Nothing reads provenance per item.
    """
    merged: list[dict[str, Any]] = []
    for block in blocks:
        previous = merged[-1] if merged else None
        parent_id = (block.get("metadata") or {}).get("parent_id")
        if (
            previous is not None
            and parent_id
            and block.get("type") == previous.get("type") == "list"
            and block.get("ordered") == previous.get("ordered")
            and (previous.get("metadata") or {}).get("parent_id") == parent_id
        ):
            previous["items"].extend(block.get("items", []))
            continue
        merged.append(block)
    return merged


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


__all__ = [
    "LETTERED_LIST_SOURCE_MARKER",
    "NUMBERING_STYLES",
    "LetteredListRecovery",
    "ListSourceElement",
    "item_label",
    "list_numbering",
    "list_start",
    "marker_numbering",
    "merge_list_blocks",
    "recover_empty_lettered_list_items",
]
