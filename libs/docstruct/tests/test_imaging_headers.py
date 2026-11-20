"""Tests for pure PNG/JPEG header dimension inspection."""
from __future__ import annotations

import struct

import pytest

from docstruct.imaging import image_dimensions


def _png_header(width: int, height: int, *, chunk_type: bytes = b"IHDR") -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + chunk_type
        + struct.pack(">II", width, height)
        + b"\x08\x02\x00\x00\x00"
    )


def _jpeg_header(width: int, height: int, *, sof_marker: int = 0xC0, prefix: bytes = b"") -> bytes:
    sof_payload = b"\x08" + struct.pack(">HH", height, width) + b"\x01"
    sof_segment = bytes([0xFF, sof_marker]) + struct.pack(">H", len(sof_payload) + 2) + sof_payload
    return b"\xff\xd8" + prefix + sof_segment + b"\xff\xd9"


def test_png_valid_dimensions():
    assert image_dimensions(_png_header(1280, 720)) == (1280, 720, ".png")


@pytest.mark.parametrize(
    "payload",
    [
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 4,  # truncated
        _png_header(100, 100, chunk_type=b"IDAT"),  # missing IHDR
        _png_header(0, 100),  # zero width
        _png_header(100, 0),  # zero height
    ],
)
def test_png_invalid_headers_return_none(payload: bytes):
    assert image_dimensions(payload) is None


@pytest.mark.parametrize("sof_marker", [0xC0, 0xC2])
def test_jpeg_valid_dimensions_with_app_segment_and_fill_bytes(sof_marker: int):
    app0 = b"\xff\xe0" + struct.pack(">H", 6) + b"JFIF"
    fill = b"\xff\xff"
    payload = _jpeg_header(640, 480, sof_marker=sof_marker, prefix=app0 + fill)
    assert image_dimensions(payload) == (640, 480, ".jpg")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"GIF89a\x01\x00\x01\x00",
        b"\xff\xd8\x00\x00\x00\x00",  # missing 0xFF marker prefix
        b"\xff\xd8\xff\xff\xff\xff",  # only fill bytes
        b"\xff\xd8\xff\xd9\x00\x00",  # EOI before SOF
        b"\xff\xd8\xff\xda\x00\x04\x00\x00",  # SOS before SOF
        b"\xff\xd8\xff\xe0\x00\x01\x00\x00",  # segment length < 2
        b"\xff\xd8\xff\xe0\x00\x20short",  # segment extends past EOF
        b"\xff\xd8\xff\xc0\x00\x05\x08\x00\x01",  # SOF length < 7
        _jpeg_header(0, 480),  # zero width
        _jpeg_header(640, 0),  # zero height
    ],
)
def test_jpeg_and_unknown_invalid_headers_return_none(payload: bytes):
    assert image_dimensions(payload) is None
