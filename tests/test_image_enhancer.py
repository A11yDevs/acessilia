"""Tests for the OCR image preprocessing helpers in ``backend.tools.image_enhancer``.

``upscale_for_ocr`` and ``rotate_for_orientation`` apply the pure decisions from
``docstruct.imaging.policy`` (Dr.DocBench PR #125): small pages are upscaled with
Lanczos before OCR, and rotated pages are straightened.
"""
from __future__ import annotations

import io

from PIL import Image

from backend.tools.image_enhancer import rotate_for_orientation, upscale_for_ocr


def jpeg(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


class TestUpscaleForOcr:
    def test_small_page_is_upscaled_2x(self):
        assert size_of(upscale_for_ocr(jpeg(400, 600))) == (800, 1200)

    def test_medium_page_is_upscaled_1_5x(self):
        assert size_of(upscale_for_ocr(jpeg(900, 1000))) == (1350, 1500)

    def test_large_page_is_unchanged(self):
        data = jpeg(2000, 3000)
        assert upscale_for_ocr(data) == data

    def test_uses_the_longest_side(self):
        # 700 x 900 -> longest side 900 -> medium band
        assert size_of(upscale_for_ocr(jpeg(700, 900))) == (1050, 1350)

    def test_invalid_bytes_are_returned_unchanged(self):
        assert upscale_for_ocr(b"not an image") == b"not an image"


class TestRotateForOrientation:
    def test_zero_angle_is_a_no_op(self):
        data = jpeg(400, 600)
        assert rotate_for_orientation(data, 0) == data

    def test_360_is_a_no_op(self):
        data = jpeg(400, 600)
        assert rotate_for_orientation(data, 360) == data

    def test_90_degrees_swaps_the_dimensions(self):
        assert size_of(rotate_for_orientation(jpeg(400, 600), 90)) == (600, 400)

    def test_180_degrees_keeps_the_dimensions(self):
        assert size_of(rotate_for_orientation(jpeg(400, 600), 180)) == (400, 600)

    def test_270_degrees_swaps_the_dimensions(self):
        assert size_of(rotate_for_orientation(jpeg(400, 600), 270)) == (600, 400)

    def test_invalid_bytes_are_returned_unchanged(self):
        assert rotate_for_orientation(b"not an image", 90) == b"not an image"
