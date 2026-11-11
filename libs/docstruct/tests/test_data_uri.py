"""Images inline as ``data:`` URIs (docstruct.data_uri).

Moved from the core's PDDL payload (#402); the core covers the policy it
passes (the raster types and the size bound) in tests/test_picture_without_page.py.
"""

from __future__ import annotations

import base64

import pytest

from docstruct.data_uri import decode_data_uri

PNG = b"\x89PNG\r\n\x1a\nsome-bytes"
TYPES = frozenset({"image/png", "image/jpeg"})


def _uri(content: bytes, media_type: str = "image/png") -> str:
    return f"data:{media_type};base64," + base64.b64encode(content).decode()


def test_a_raster_uri_is_decoded() -> None:
    assert decode_data_uri(_uri(PNG), media_types=TYPES, max_bytes=1024) == PNG


@pytest.mark.parametrize(
    "src",
    [None, 42, "https://example.test/a.png", _uri(PNG, "image/svg+xml"), "data:image/png,raw",
     "data:image/png;base64,***", "data:image/png;base64,", "image/png;base64,aGVsbG8="],
)
def test_anything_else_is_none(src) -> None:
    assert decode_data_uri(src, media_types=TYPES, max_bytes=1024) is None


def test_the_media_types_are_the_caller_s() -> None:
    assert decode_data_uri(_uri(PNG), media_types={"image/jpeg"}, max_bytes=1024) is None


def test_the_size_bound_is_inclusive_and_on_the_decoded_bytes() -> None:
    assert decode_data_uri(_uri(PNG), media_types=TYPES, max_bytes=len(PNG)) == PNG
    assert decode_data_uri(_uri(PNG), media_types=TYPES, max_bytes=len(PNG) - 1) is None


def test_case_and_whitespace() -> None:
    encoded = base64.b64encode(PNG).decode()
    src = f" DATA:IMAGE/PNG;BASE64,{encoded[:5]}\n {encoded[5:]} "

    assert decode_data_uri(src, media_types=TYPES, max_bytes=1024) == PNG
