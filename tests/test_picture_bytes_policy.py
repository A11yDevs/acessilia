"""How a picture's pixels are obtained (#402).

Characterization written on develop before ``_extract_picture_bytes`` was
decomposed: the clip geometry and the ``data:`` URI decoding moved to
docstruct (``best_effort_clip``, ``decode_data_uri``), and the render
fallbacks stayed in the core. The render itself is
replaced here; tests/test_picture_crop_render.py and
tests/test_picture_without_page.py run it against the fake Toolbox.
"""

from __future__ import annotations

import base64
import math
from pathlib import Path

import pytest
from acessilia_sdk.toolbox import ToolboxCapabilityError, ToolboxIncompatibleEndpoint
from acessilia_sdk.toolbox.clients.pdf import RenderedPage

from docstruct.data_uri import decode_data_uri
from docstruct.geometry.boxes import best_effort_clip
from backend.core.manifest.models import BoundingBox, Provenance
from tests.pddl_support import build_element
from backend.core.pipeline.enrichment import common as enrichment_common


def _picture(box=None, origin="TOPLEFT", page=2, src=None):
    element = build_element("pic", "picture", metadata={"src": src} if src is not None else None)
    if page is None:
        element.provenance = []
    else:
        bbox = None if box is None else BoundingBox(
            left=box[0], top=box[1], right=box[2], bottom=box[3], coord_origin=origin)
        element.provenance = [Provenance(page_number=page, bbox=bbox)]
    return element


class _Renders:
    def __init__(self, monkeypatch, *, clip_result=None, clip_error=None, page_error=None):
        self.calls = []
        self._clip_result = clip_result
        self._clip_error = clip_error
        self._page_error = page_error
        monkeypatch.setattr(enrichment_common, "_toolbox_render", self)

    def __call__(self, source, page_number, **kwargs):
        self.calls.append((page_number, kwargs["clip"], kwargs["clip_origin"]))
        if kwargs["clip"] is None:
            if self._page_error:
                raise self._page_error
            return RenderedPage(image=b"page", clip=(0, 0, 600, 800), document={})
        if self._clip_error:
            raise self._clip_error
        return RenderedPage(image=b"crop", clip=self._clip_result or kwargs["clip"], document={})


def _extract(element, **kwargs):
    return enrichment_common._extract_picture_bytes(Path("doc.pdf"), element, kwargs.pop("fallback", None), **kwargs)


def test_a_boxed_picture_is_its_crop(monkeypatch) -> None:
    renders = _Renders(monkeypatch)

    assert _extract(_picture((10, 20, 110, 220))) == (b"crop", 2)
    assert renders.calls == [(2, (10.0, 20.0, 110.0, 220.0), "TOPLEFT")]


def test_a_picture_without_a_box_is_its_page(monkeypatch) -> None:
    renders = _Renders(monkeypatch)

    assert _extract(_picture(None)) == (b"page", 2)
    assert renders.calls == [(2, None, "TOPLEFT")]


def test_a_refused_box_falls_back_to_the_page(monkeypatch) -> None:
    renders = _Renders(monkeypatch, clip_error=ToolboxCapabilityError("box outside the page"))

    assert _extract(_picture((10, 20, 110, 220))) == (b"page", 2)
    assert [call[1] for call in renders.calls] == [(10.0, 20.0, 110.0, 220.0), None]


def test_an_incompatible_endpoint_is_not_a_refusal(monkeypatch) -> None:
    _Renders(monkeypatch, clip_error=ToolboxIncompatibleEndpoint("old toolbox"))

    assert _extract(_picture((10, 20, 110, 220))) == (None, 2)


@pytest.mark.parametrize(("applied", "expected"), [
    ((10, 20, 13.9, 220), b"page"), ((10, 20, 110, 23.9), b"page"), ((10, 20, 14, 24), b"crop"),
])
def test_a_sliver_of_a_box_falls_back_to_the_page(monkeypatch, applied, expected) -> None:
    _Renders(monkeypatch, clip_result=applied)

    assert _extract(_picture((10, 20, 110, 220)))[0] == expected


def test_any_other_failure_leaves_the_picture_without_an_image(monkeypatch) -> None:
    _Renders(monkeypatch, clip_error=RuntimeError("toolbox down"))

    assert _extract(_picture((10, 20, 110, 220))) == (None, 2)


def test_a_failing_page_render_leaves_the_picture_without_an_image(monkeypatch) -> None:
    _Renders(monkeypatch, page_error=RuntimeError("toolbox down"))

    assert _extract(_picture(None)) == (None, 2)


def test_without_provenance_the_fallback_page_is_rendered(monkeypatch) -> None:
    renders = _Renders(monkeypatch)

    assert _extract(_picture(page=None), fallback=3) == (b"page", 3)
    assert renders.calls == [(3, None, "TOPLEFT")]


def test_without_any_page_the_embedded_image_is_read(monkeypatch) -> None:
    renders = _Renders(monkeypatch)
    src = "data:image/jpg;base64," + base64.b64encode(b"jpeg-bytes").decode()

    assert _extract(_picture(page=None, src=src)) == (b"jpeg-bytes", 0)
    assert _extract(_picture(page=None), fallback=0) == (None, 0)
    assert renders.calls == []


@pytest.mark.parametrize(
    ("box", "origin", "expected"),
    [
        pytest.param((10, 700, 110, 600), "BOTTOMLEFT", ((10.0, 700.0, 110.0, 600.0), "BOTTOMLEFT"), id="bottom-left"),
        pytest.param((10, 20, 110, 220), "TOPLEFT", ((10.0, 20.0, 110.0, 220.0), "TOPLEFT"), id="top-left"),
        pytest.param((10, 700, 110, 600), "UNKNOWN", ((10.0, 700.0, 110.0, 600.0), "BOTTOMLEFT"), id="inferred-up"),
        pytest.param((10, 20, 110, 220), "UNKNOWN", ((10.0, 20.0, 110.0, 220.0), "TOPLEFT"), id="inferred-down"),
        pytest.param((10, 20, 110, 20), "UNKNOWN", ((10.0, 20.0, 110.0, 20.0), "TOPLEFT"), id="flat-inferred-down"),
    ],
)
def test_the_clip_and_its_origin(box, origin, expected) -> None:
    assert best_effort_clip(_picture(box, origin).provenance[0].bbox) == expected


def test_no_clip_without_a_usable_box() -> None:
    assert best_effort_clip(None) == (None, "TOPLEFT")
    assert best_effort_clip(_picture(None).provenance[0].bbox) == (None, "TOPLEFT")
    element = _picture((10, 20, 110, 220))
    element.provenance[0].bbox.right = math.inf
    assert best_effort_clip(element.provenance[0].bbox) == (None, "TOPLEFT")


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        pytest.param("data:image/png;base64, aGVs\nbG8= ", b"hello", id="whitespace-in-payload"),
        pytest.param(" DATA:Image/JPEG;BASE64,aGVsbG8=", b"hello", id="case-and-leading-space"),
        pytest.param("data:image/png;charset=x;base64,aGVsbG8=", None, id="extra-parameter"),
        pytest.param("data:image/png;base64,aGVsbG8", None, id="unpadded"),
        pytest.param(42, None, id="not-a-string"),
    ],
)
def test_the_embedded_image(src, expected) -> None:
    decoded = decode_data_uri(src, media_types=enrichment_common._EMBEDDED_PICTURE_TYPES,
                              max_bytes=enrichment_common._EMBEDDED_PICTURE_MAX_BYTES)
    assert decoded == expected
