"""Letterheads: a logo and the page header lines beside it (pure).

Moved from the core's PDDL payload (#402). An institutional header
("University of X / Department of Y" next to the logo) reaches the manifest as
page header lines and an unrelated picture, so the reader got the lines apart
and a long description of a logo that repeats them. These rules find which
pictures and lines belong together; deciding which elements are header lines,
and writing the merged paragraph, stay with the caller.

Boxes are ``(left, top, right, bottom)`` on the unit page, measured from the top.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from docstruct.fusion.noise import PAGE_NUMBER_MARGIN

#: Height share of the page by which a picture may miss a header line and
#: still sit beside it (the line's box is tighter than the logo's).
LETTERHEAD_TOLERANCE = 0.01
#: Width share of the page a header line may stand away from the picture and
#: still be beside it; a running header across the page is not.
LETTERHEAD_MAX_GAP = 0.05
#: Tallest picture, as a share of the page height, read as a logo: a figure
#: crossing the header band is content, and keeps its description.
LETTERHEAD_MAX_HEIGHT = PAGE_NUMBER_MARGIN

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class PlacedItem:
    """A picture or a header line, with what the grouping needs of it."""

    id: str
    page: int
    reading_order: int
    box: Box


def is_beside(picture_box: Box, line_box: Box) -> bool:
    """Whether a header line overlaps the picture's height and stands next to it."""
    horizontal_gap = max(line_box[0] - picture_box[2], picture_box[0] - line_box[2])
    return (
        line_box[1] <= picture_box[3] + LETTERHEAD_TOLERANCE
        and picture_box[1] <= line_box[3] + LETTERHEAD_TOLERANCE
        and horizontal_gap <= LETTERHEAD_MAX_GAP
    )


def is_logo_sized(box: Box) -> bool:
    """Whether a picture is short enough to be a logo (``LETTERHEAD_MAX_HEIGHT``)."""
    return box[3] - box[1] <= LETTERHEAD_MAX_HEIGHT


def letterhead_groups(
    pictures: Iterable[PlacedItem], lines: Iterable[PlacedItem]
) -> dict[str, list[str]]:
    """Logos and the header lines beside them, keyed by the first in reading order.

    Each value lists the group's ids in reading order. Only logo-sized
    pictures take part. A picture joins the lines beside it on its page; two
    pictures form one group only when they share a line, so two institutions'
    headers on a page stay apart. A picture with no line beside it, and a line
    with no picture, belong to no group. Items keep the order they are given
    in when they tie on reading order.
    """
    by_page_lines: dict[int, list[PlacedItem]] = {}
    by_page_pictures: dict[int, list[PlacedItem]] = {}
    for line in lines:
        by_page_lines.setdefault(line.page, []).append(line)
    for picture in pictures:
        if is_logo_sized(picture.box):
            by_page_pictures.setdefault(picture.page, []).append(picture)

    groups: dict[str, list[str]] = {}
    for page, page_pictures in by_page_pictures.items():
        components: list[dict[str, PlacedItem]] = []
        for picture in page_pictures:
            beside = [
                line
                for line in by_page_lines.get(page, [])
                if is_beside(picture.box, line.box)
            ]
            if not beside:
                continue
            component = {picture.id: picture}
            component.update((line.id, line) for line in beside)
            for other in [item for item in components if item.keys() & component.keys()]:
                component.update(other)
                components.remove(other)
            components.append(component)
        for component in components:
            ordered = sorted(component.values(), key=lambda item: item.reading_order)
            groups[ordered[0].id] = [item.id for item in ordered]
    return groups


__all__ = [
    "LETTERHEAD_MAX_GAP",
    "LETTERHEAD_MAX_HEIGHT",
    "LETTERHEAD_TOLERANCE",
    "PlacedItem",
    "is_beside",
    "is_logo_sized",
    "letterhead_groups",
]
