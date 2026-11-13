"""The formula chain runs its steps in order and decides nothing (ADR-0017).

Offline: respx answers ``pdf.render``, the PNG download, ``math.recognize``,
``math.convert`` and ``math.verbalize`` the way the Toolbox does.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import parse_qs

import httpx
import pytest

from acessilia_sdk.operations.formula import (
    FormulaChain,
    Step,
    crop_formula_region,
    formula_chain,
    recognize_formula,
    speak_formula,
)
from acessilia_sdk.toolbox import ToolboxInvalidInput, ToolboxProviderUnavailable
from acessilia_sdk.toolbox.clients.math import ToolboxMathClient
from acessilia_sdk.toolbox.clients.pdf import ToolboxPdfClient

BASE = "http://toolbox.test"
SOURCE_ID = "sha256:" + "a" * 64
PNG = b"\x89PNG\r\n\x1a\nformula-crop"
PNG_ID = "sha256:" + hashlib.sha256(PNG).hexdigest()


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float
    coord_origin: str | None = "TOPLEFT"


BOX = Box(100, 200, 300, 240)


def _render_answer(clip: dict[str, float]) -> dict:
    return {
        "status": "succeeded",
        "capability": "pdf.render@2",
        "provider": "pymupdf-pdf",
        "document": {
            "artifact_id": PNG_ID,
            "media_type": "image/png",
            "size_bytes": len(PNG),
            "page_number": 3,
            "page_count": 5,
            "page_width": 595,
            "page_height": 842,
            "clip": clip,
            "scale": 2.78,
            "dpi": 200.0,
            "width_px": 556,
            "height_px": 111,
            "source_media_type": "application/pdf",
            "source_filename": "doc.pdf",
        },
    }


def _succeeded(capability: str, document: dict) -> dict:
    return {"status": "succeeded", "capability": capability, "provider": "p", "document": document}


RECOGNIZED = _succeeded(
    "math.recognize",
    {
        "formulas": [
            {"latex": "$x^2$", "confidence": 0.4, "page": 1, "bbox": None},
            {"latex": "E = mc^2", "confidence": 0.9, "page": 1, "bbox": None},
            {"latex": "  ", "confidence": 1.0},
        ]
    },
)


def _parameters(request: httpx.Request) -> dict:
    body = request.content
    if b"Content-Disposition" in body:
        part = body.split(b'name="parameters"', 1)[1].split(b"\r\n\r\n", 1)[1]
        return json.loads(part.split(b"\r\n", 1)[0])
    return json.loads(parse_qs(body.decode())["parameters"][0])


@pytest.fixture
def pdf() -> ToolboxPdfClient:
    return ToolboxPdfClient(base_url=BASE, provider="pymupdf-pdf", timeout_seconds=5)


@pytest.fixture
def math() -> ToolboxMathClient:
    return ToolboxMathClient(
        base_url=BASE,
        provider="pp-formulanet",
        transform_provider="math-speech",
        timeout_seconds=5,
    )


def _mock_render(respx_mock, clip=None):
    clip = clip or {"left": 100, "top": 200, "right": 300, "bottom": 240}
    route = respx_mock.post(f"{BASE}/v1/capabilities/pdf.render:execute").mock(
        return_value=httpx.Response(200, json=_render_answer(clip))
    )
    respx_mock.get(f"{BASE}/v1/artifacts/{PNG_ID}").mock(
        return_value=httpx.Response(200, content=PNG)
    )
    return route


def _mock_math(respx_mock, recognized=RECOGNIZED):
    routes = {}
    routes["recognize"] = respx_mock.post(f"{BASE}/v1/capabilities/math.recognize:execute").mock(
        return_value=httpx.Response(200, json=recognized)
    )
    routes["convert"] = respx_mock.post(f"{BASE}/v1/capabilities/math.convert:execute").mock(
        return_value=httpx.Response(
            200, json=_succeeded("math.convert", {"latex": "E = mc^2", "mathml": "<math/>"})
        )
    )
    routes["verbalize"] = respx_mock.post(f"{BASE}/v1/capabilities/math.verbalize:execute").mock(
        return_value=httpx.Response(
            200,
            json=_succeeded("math.verbalize", {"latex": "E = mc^2", "verbalized": "E igual a m c ao quadrado"}),
        )
    )
    return routes


# --- crop ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crop_renders_the_box_at_200_dpi(respx_mock, pdf) -> None:
    route = _mock_render(respx_mock)

    crop = await crop_formula_region(pdf, None, page_number=3, box=BOX, artifact_id=SOURCE_ID)

    assert crop.image == PNG
    assert crop.clip == (100.0, 200.0, 300.0, 240.0)
    assert crop.reason is None
    assert _parameters(route.calls.last.request) == {
        "page_number": 3,
        "dpi": 200,
        "clip": {"left": 100, "top": 200, "right": 300, "bottom": 240, "origin": "TOPLEFT"},
    }
    assert crop.step == Step(
        "pdf.render",
        "pymupdf-pdf",
        {"page_number": 3, "dpi": 200, "clip": (100.0, 200.0, 300.0, 240.0), "clip_origin": "TOPLEFT"},
    )


@pytest.mark.asyncio
async def test_crop_keeps_a_bottom_left_box_for_the_toolbox_to_convert(respx_mock, pdf) -> None:
    route = _mock_render(respx_mock)

    await crop_formula_region(
        pdf, None, page_number=3, box=Box(100, 642, 300, 602, "BOTTOMLEFT"), artifact_id=SOURCE_ID
    )

    assert _parameters(route.calls.last.request)["clip"]["origin"] == "BOTTOMLEFT"


@pytest.mark.parametrize(
    ("page_number", "box", "reason"),
    [
        (0, BOX, "no page"),
        (3, None, "no usable box"),
        (3, Box(float("nan"), 200, 300, 240), "no usable box"),
    ],
)
@pytest.mark.asyncio
async def test_no_crop_without_a_request_never_the_whole_page(
    respx_mock, pdf, page_number, box, reason
) -> None:
    route = _mock_render(respx_mock)

    crop = await crop_formula_region(pdf, None, page_number=page_number, box=box, artifact_id=SOURCE_ID)

    assert (crop.image, crop.reason, crop.step) == (None, reason, None)
    assert not route.called


@pytest.mark.asyncio
async def test_a_crop_thinner_than_the_minimum_side_is_no_crop(respx_mock, pdf) -> None:
    _mock_render(respx_mock, {"left": 100, "top": 200, "right": 300, "bottom": 203})

    crop = await crop_formula_region(pdf, None, page_number=3, box=BOX, artifact_id=SOURCE_ID)

    assert crop.image is None
    assert crop.reason == "crop too small"
    assert crop.clip == (100.0, 200.0, 300.0, 203.0)
    assert crop.step is not None


@pytest.mark.asyncio
async def test_a_render_failure_is_raised_not_turned_into_no_crop(respx_mock, pdf) -> None:
    respx_mock.post(f"{BASE}/v1/capabilities/pdf.render:execute").mock(
        return_value=httpx.Response(503, json={"detail": "down"})
    )

    with pytest.raises(ToolboxProviderUnavailable):
        await crop_formula_region(pdf, None, page_number=3, box=BOX, artifact_id=SOURCE_ID)


# --- recognize -------------------------------------------------------------


@pytest.mark.asyncio
async def test_recognize_uploads_the_crop_and_ranks_the_candidates(respx_mock, math) -> None:
    routes = _mock_math(respx_mock)

    found = await recognize_formula(math, PNG)

    request = routes["recognize"].calls.last.request
    assert b'filename="formula.png"' in request.content
    assert PNG in request.content
    assert [c["latex"] for c in found.candidates] == ["E = mc^2", "x^2"]
    assert found.step == Step("math.recognize", "pp-formulanet", {"language": "pt-BR"})


@pytest.mark.asyncio
async def test_an_answer_without_latex_is_no_candidate(respx_mock, math) -> None:
    _mock_math(respx_mock, _succeeded("math.recognize", {"formulas": []}))

    found = await recognize_formula(math, PNG)

    assert found.candidates == []


@pytest.mark.asyncio
async def test_a_refused_crop_raises_invalid_input(respx_mock, math) -> None:
    respx_mock.post(f"{BASE}/v1/capabilities/math.recognize:execute").mock(
        return_value=httpx.Response(400, json={"code": "invalid_input", "message": "not an image"})
    )

    with pytest.raises(ToolboxInvalidInput):
        await recognize_formula(math, PNG)


@pytest.mark.asyncio
async def test_the_temporary_crop_is_removed_even_when_recognition_fails(
    respx_mock, math, monkeypatch, tmp_path
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    respx_mock.post(f"{BASE}/v1/capabilities/math.recognize:execute").mock(
        return_value=httpx.Response(503, json={"detail": "down"})
    )

    with pytest.raises(ToolboxProviderUnavailable):
        await recognize_formula(math, PNG)
    assert list(tmp_path.iterdir()) == []


# --- speak -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_speak_converts_and_verbalizes_with_the_transform_provider(respx_mock, math) -> None:
    routes = _mock_math(respx_mock)

    speech = await speak_formula(math, "E = mc^2", language="en")

    assert speech.mathml == "<math/>"
    assert speech.verbalization == "E igual a m c ao quadrado"
    assert _parameters(routes["convert"].calls.last.request)["direction"] == "latex-to-mathml"
    assert b'name="language"\r\n\r\nen\r\n' in routes["verbalize"].calls.last.request.content
    assert [s.capability for s in speech.steps] == ["math.convert", "math.verbalize"]
    assert {s.provider for s in speech.steps} == {"math-speech"}


# --- chain -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_chain_runs_every_step_in_order(respx_mock, pdf, math) -> None:
    _mock_render(respx_mock)
    _mock_math(respx_mock)

    chain = await formula_chain(pdf, math, None, page_number=3, box=BOX, artifact_id=SOURCE_ID)

    assert isinstance(chain, FormulaChain)
    assert chain.latex == "E = mc^2"
    assert chain.speech is not None and chain.speech.mathml == "<math/>"
    assert [s.capability for s in chain.steps] == [
        "pdf.render",
        "math.recognize",
        "math.convert",
        "math.verbalize",
    ]
    calls = [call.request.url.path for call in respx_mock.calls]
    assert calls == [
        "/v1/capabilities/pdf.render:execute",
        f"/v1/artifacts/{PNG_ID}",
        "/v1/capabilities/math.recognize:execute",
        "/v1/capabilities/math.convert:execute",
        "/v1/capabilities/math.verbalize:execute",
    ]


@pytest.mark.asyncio
async def test_the_chain_speaks_the_chosen_candidate(respx_mock, pdf, math) -> None:
    _mock_render(respx_mock)
    routes = _mock_math(respx_mock)

    chain = await formula_chain(
        pdf, math, None, page_number=3, box=BOX, artifact_id=SOURCE_ID, candidate=2
    )

    assert chain.latex == "x^2"
    assert b"x^2" in routes["convert"].calls.last.request.content


@pytest.mark.asyncio
async def test_the_chain_stops_without_a_crop_or_a_candidate(respx_mock, pdf, math) -> None:
    _mock_render(respx_mock)
    routes = _mock_math(respx_mock)

    no_crop = await formula_chain(pdf, math, None, page_number=3, box=None)
    third = await formula_chain(
        pdf, math, None, page_number=3, box=BOX, artifact_id=SOURCE_ID, candidate=3
    )

    assert (no_crop.latex, no_crop.candidates, no_crop.speech) == ("", None, None)
    assert no_crop.steps == ()
    assert third.latex == "" and third.speech is None
    assert [s.capability for s in third.steps] == ["pdf.render", "math.recognize"]
    assert routes["recognize"].call_count == 1
    assert not routes["convert"].called


@pytest.mark.asyncio
async def test_the_candidate_is_one_based(pdf, math) -> None:
    with pytest.raises(ValueError, match="1-based"):
        await formula_chain(pdf, math, None, page_number=3, box=BOX, candidate=0)
