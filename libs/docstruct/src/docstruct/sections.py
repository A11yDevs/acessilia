"""Section compatibility and heading-hierarchy helpers."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HeadingGap:
    """A heading whose level violates the sequential hierarchy contract."""

    index: int
    previous_level: int
    current_level: int


def find_heading_gaps(levels: Sequence[int]) -> list[HeadingGap]:
    """Return every position in ``levels`` that breaks the heading hierarchy.

    The first heading must be level 1; each subsequent heading must sit in
    ``[2, min(previous + 1, 6)]``.
    """
    gaps: list[HeadingGap] = []
    previous = 0
    for index, level in enumerate(levels):
        invalid_first = previous == 0 and level != 1
        invalid_successor = previous > 0 and (level < 2 or level > min(previous + 1, 6))
        if invalid_first or invalid_successor:
            gaps.append(
                HeadingGap(index=index, previous_level=previous, current_level=level)
            )
        previous = level
    return gaps


def repair_heading_levels(levels: Sequence[int]) -> list[int]:
    """Repair a heading-level sequence so every transition obeys the hierarchy.

    The first heading becomes level 1; each subsequent heading is clamped to
    ``[2, min(previous + 1, 6)]`` using the already-repaired predecessor level.
    """
    repaired: list[int] = []
    previous = 0
    for raw_level in levels:
        level = 1 if previous == 0 else max(2, min(raw_level, previous + 1, 6))
        repaired.append(level)
        previous = level
    return repaired


def explicit_section_title(section: dict[str, Any]) -> dict[str, Any] | None:
    blocks = section.get("blocks", [])
    if not section.get("title") or not blocks:
        return None
    first = blocks[0]
    if (
        first.get("type") == "heading"
        and first.get("title", first.get("text", "")) == section["title"]
        and first.get("level", 1) == section.get("level", 1)
    ):
        return first
    return None


def section_body_blocks(section: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = section.get("blocks", [])
    return blocks[1:] if explicit_section_title(section) is not None else blocks


def section_title_alias(section: dict[str, Any]) -> str:
    first = explicit_section_title(section)
    if first is not None and first.get("id") != section.get("id"):
        return first.get("id", "")
    return ""


__all__ = [
    "HeadingGap",
    "explicit_section_title",
    "find_heading_gaps",
    "repair_heading_levels",
    "section_body_blocks",
    "section_title_alias",
]
