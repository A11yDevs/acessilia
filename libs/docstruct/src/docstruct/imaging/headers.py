"""Pure PNG and JPEG header dimension inspection (standard library only)."""
from __future__ import annotations

import struct

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
_JPEG_STOP_MARKERS = frozenset({0xD9, 0xDA})


def _png_dimensions(payload: bytes) -> tuple[int, int, str] | None:
    if len(payload) < 24 or payload[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", payload[16:24])
    return (width, height, ".png") if width and height else None


def _jpeg_dimensions(payload: bytes) -> tuple[int, int, str] | None:
    position = 2
    total = len(payload)
    while position + 4 <= total:
        if payload[position] != 0xFF:
            return None
        while position < total and payload[position] == 0xFF:
            position += 1
        if position >= total:
            return None
        marker = payload[position]
        position += 1
        if marker in _JPEG_STOP_MARKERS:
            return None
        length = int.from_bytes(payload[position : position + 2], "big")
        if length < 2 or position + length > total:
            return None
        if marker in _JPEG_SOF_MARKERS:
            if length < 7:
                return None
            height, width = struct.unpack(">HH", payload[position + 3 : position + 7])
            return (width, height, ".jpg") if width and height else None
        position += length
    return None


def image_dimensions(payload: bytes) -> tuple[int, int, str] | None:
    """Read ``(width, height, suffix)`` from a PNG or JPEG header without decoding pixels.

    Returns ``None`` when ``payload`` is not a valid PNG/JPEG header or reports
    a zero dimension. ``suffix`` is ``".png"`` or ``".jpg"``.
    """
    if payload.startswith(_PNG_SIGNATURE):
        return _png_dimensions(payload)
    if payload.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(payload)
    return None


__all__ = ["image_dimensions"]
