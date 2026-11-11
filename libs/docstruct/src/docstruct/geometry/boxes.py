"""Bounding boxes that carry their coordinate origin.

Pure: zero external dependencies, standard library only.

Providers disagree on where y starts: PyMuPDF uses the top-left corner,
PDF and Docling the bottom-left one, and some say nothing. A box therefore
travels with its ``coord_origin`` (``TOPLEFT``, ``BOTTOMLEFT`` or
``UNKNOWN``), and every conversion below states which frame it returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from docstruct.types import BBox


def is_bottom_left(coord_origin: str | None, top: float, bottom: float) -> bool:
    """Whether a box's y axis grows upwards (the PDF/Docling default).

    An explicit origin wins. An unknown or missing one is decided by the
    geometry: with y growing upwards the top edge has the larger value.
    """
    origin = str(coord_origin or "UNKNOWN").upper()
    if origin == "BOTTOMLEFT":
        return True
    if origin == "TOPLEFT":
        return False
    return top > bottom


@dataclass(frozen=True)
class OrientedBox:
    """A box as a provider stored it, with the origin of its y axis."""

    left: float
    top: float
    right: float
    bottom: float
    coord_origin: str | None = "UNKNOWN"

    @property
    def bottom_left(self) -> bool:
        return is_bottom_left(self.coord_origin, self.top, self.bottom)

    def top_down(self) -> BBox:
        """``(x0, y0, x1, y1)`` with y growing downwards, whatever the origin.

        A bottom-left box is mirrored (``y -> -y``), which keeps every
        comparison between boxes right without knowing the page height.
        Only differences and orderings are meaningful: a mirrored ``y0`` or
        ``y1`` is negative, so never compare it with a fixed position such as
        ``0``. ``page_fractions`` gives positions on the page instead.
        """
        if self.bottom_left:
            return (self.left, -self.top, self.right, -self.bottom)
        return (self.left, self.top, self.right, self.bottom)

    def page_fractions(self, width: float | None, height: float | None) -> BBox | None:
        """``(x0, y0, x1, y1)`` as fractions of the page, top-left origin.

        ``None`` when the page size is unknown or zero.
        """
        if not width or not height:
            return None
        top, bottom = self.top, self.bottom
        if self.bottom_left:
            top, bottom = height - top, height - bottom
        return (self.left / width, top / height, self.right / width, bottom / height)


class VerticalBox(Protocol):
    """What :func:`downward_edges` reads of a box (read-only)."""

    @property
    def top(self) -> float: ...

    @property
    def bottom(self) -> float: ...

    @property
    def coord_origin(self) -> str | None: ...


def downward_edges(box: VerticalBox) -> tuple[float, float]:
    """``(upper, lower)`` edges in a downward axis, whatever the box's origin."""
    if box.coord_origin == "BOTTOMLEFT":
        return -box.top, -box.bottom
    return min(box.top, box.bottom), max(box.top, box.bottom)


class PageBox(VerticalBox, Protocol):
    """A box on a page, with its four edges and origin (read-only)."""

    @property
    def left(self) -> float: ...

    @property
    def right(self) -> float: ...


def holds_point(box: BBox, x: float, y: float, margin: float) -> bool:
    """Whether ``(x, y)`` lies in ``box``, or within ``margin`` of it.

    ``box`` is ``(left, top, right, bottom)`` in one frame with the point; its
    vertical edges may come in either order.
    """
    left, top, right, bottom = box
    top, bottom = min(top, bottom), max(top, bottom)
    return left - margin <= x <= right + margin and top - margin <= y <= bottom + margin


__all__ = [
    "OrientedBox",
    "PageBox",
    "VerticalBox",
    "downward_edges",
    "holds_point",
    "is_bottom_left",
]
