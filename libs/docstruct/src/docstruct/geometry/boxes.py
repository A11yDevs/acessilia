"""Bounding boxes that carry their coordinate origin.

Pure: zero external dependencies, standard library only.

Providers disagree on where y starts: PyMuPDF uses the top-left corner,
PDF and Docling the bottom-left one, and some say nothing. A box therefore
travels with its ``coord_origin`` (``TOPLEFT``, ``BOTTOMLEFT`` or
``UNKNOWN``), and every conversion below states which frame it returns.
"""
from __future__ import annotations

from dataclasses import dataclass

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


__all__ = ["OrientedBox", "is_bottom_left"]
