"""The page judge renders a page, then judges two candidates, and decides nothing.

Offline: respx answers ``pdf.render``, the PNG download and
``document.adjudicate.page`` the way the Toolbox does (ADR-0017, #470 phase 4).
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs

import httpx
import pytest

from acessilia_sdk.operations.formula import Step
from acessilia_sdk.operations.page_judge import (
    JUDGE_PAGE_DPI,
    JUDGE_PAGE_MAX_SIDE,
    judge_page,
    page_judgement,
    render_judge_page,
)
from acessilia_sdk.toolbox import ToolboxInvalidInput, ToolboxProviderUnavailable
from acessilia_sdk.toolbox.clients.adjudicate import ToolboxAdjudicateClient
from acessilia_sdk.toolbox.clients.pdf import ToolboxPdfClient

BASE = "http://toolbox.test"
SOURCE_ID = "sha256:" + "b" * 64
PNG = b"\x89PNG\r\n\x1a\njudge-page"
PNG_ID = "sha256:" + hashlib.sha256(PNG).hexdigest()


def _render_answer() -> dict:
    return {
        "status": "succeeded",
        "capability": "pdf.render@2",
        "provider": "pymupdf-pdf",
        "document": {
            "artifact_id": PNG_ID,
            "media_type": "image/png",
            "size_bytes": len(PNG),
            "page_number": 2,
            "page_count": 4,
            "page_width": 595,
            "page_height": 842,
            "clip": {"left": 0, "top": 0, "right": 595, "bottom": 842},
            "scale": 1.9,
            "dpi": 137.0,
            "width_px": 1131,
            "height_px": 1600,
            "source_media_type": "application/pdf",
            "source_filename": "doc.pdf",
        },
    }


def _judged(document) -> dict:
    return {
        "status": "succeeded",
        "capability": "document.adjudicate.page@1",
        "provider": "qwen3-vl-8b",
        "document": document,
    }


def _parameters(request: httpx.Request) -> dict:
    """The ``parameters`` field of a request, multipart or form-encoded."""
    body = request.content
    if b"Content-Disposition" in body:
        part = body.split(b'name="parameters"', 1)[1].split(b"\r\n\r\n", 1)[1]
        return json.loads(part.split(b"\r\n", 1)[0])
    return json.loads(parse_qs(body.decode())["parameters"][0])


def _no_cache(request: httpx.Request) -> bool:
    """Whether the request asks the Toolbox to skip its cache (a form field)."""
    body = request.content
    if b"Content-Disposition" in body:
        return b'name="no_cache"' in body
    return "no_cache" in parse_qs(body.decode())


@pytest.fixture
def pdf() -> ToolboxPdfClient:
    return ToolboxPdfClient(base_url=BASE, provider="pymupdf-pdf", timeout_seconds=5)


@pytest.fixture
def adjudicate() -> ToolboxAdjudicateClient:
    return ToolboxAdjudicateClient(base_url=BASE, provider="qwen3-vl-8b", timeout_seconds=5)


def _mock_render(respx_mock):
    route = respx_mock.post(f"{BASE}/v1/capabilities/pdf.render:execute").mock(
        return_value=httpx.Response(200, json=_render_answer())
    )
    respx_mock.get(f"{BASE}/v1/artifacts/{PNG_ID}").mock(
        return_value=httpx.Response(200, content=PNG)
    )
    return route


def _mock_judge(respx_mock, document):
    return respx_mock.post(f"{BASE}/v1/capabilities/document.adjudicate.page:execute").mock(
        return_value=httpx.Response(200, json=_judged(document))
    )


# --- render -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_whole_page_is_rendered_bounded_for_the_judge(respx_mock, pdf) -> None:
    route = _mock_render(respx_mock)

    page = await render_judge_page(pdf, None, page_number=2, artifact_id=SOURCE_ID)

    assert page.image == PNG
    assert page.page_number == 2
    assert (JUDGE_PAGE_DPI, JUDGE_PAGE_MAX_SIDE) == (144, 1600)
    sent = _parameters(route.calls.last.request)
    assert sent["page_number"] == 2 and sent["dpi"] == 144 and sent["max_side"] == 1600
    assert "clip" not in sent, "the whole page, not a region"
    assert page.step == Step(
        "pdf.render", "pymupdf-pdf", {"page_number": 2, "dpi": 144, "max_side": 1600}
    )


@pytest.mark.asyncio
async def test_a_render_error_is_raised_as_it_is(respx_mock, pdf) -> None:
    respx_mock.post(f"{BASE}/v1/capabilities/pdf.render:execute").mock(
        return_value=httpx.Response(400, json={"code": "invalid_input", "message": "page 9"})
    )

    with pytest.raises(ToolboxInvalidInput):
        await render_judge_page(pdf, None, page_number=9, artifact_id=SOURCE_ID)


# --- judge ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_judge_gets_both_candidates_and_its_answer_is_read(respx_mock, adjudicate) -> None:
    route = _mock_judge(respx_mock, {"pB": 0.83, "pB_ab": 0.9, "pA_ba": 0.24, "model": "qwen3-vl-8b"})

    judgement = await judge_page(adjudicate, PNG, "page as held", "the other reading")

    assert _parameters(route.calls.last.request) == {
        "candidate_a": "page as held",
        "candidate_b": "the other reading",
        "prompt": "base",
    }
    assert PNG in route.calls.last.request.content
    assert judgement.p_b == pytest.approx(0.83)
    assert (judgement.p_b_ab, judgement.p_a_ba, judgement.model) == (0.9, 0.24, "qwen3-vl-8b")
    assert judgement.step == Step("document.adjudicate.page", "qwen3-vl-8b", {"prompt": "base"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document",
    [{"pB": 1.5}, {"pB": "n/a"}, {"pB": None}, {}, ["not", "an", "object"], None],
    ids=["out of range", "not a number", "null", "absent", "a list", "no document"],
)
async def test_an_answer_without_a_valid_pb_is_reported_not_decided(
    respx_mock, adjudicate, document
) -> None:
    _mock_judge(respx_mock, document)

    judgement = await judge_page(adjudicate, PNG, "a", "b")

    assert judgement.p_b is None


@pytest.mark.asyncio
async def test_pb_is_read_as_page_judgement_probability_reads_it(respx_mock, adjudicate) -> None:
    """Whatever ``float()`` reads, in [0, 1]: a numeric string and a boolean
    too (review of #605). The core reads ``pB`` the same way today."""
    for value, expected in (("0.5", 0.5), (True, 1.0), (False, 0.0), (0, 0.0), (1, 1.0)):
        _mock_judge(respx_mock, {"pB": value})

        judgement = await judge_page(adjudicate, PNG, "a", "b")

        assert judgement.p_b == expected, value


@pytest.mark.asyncio
@pytest.mark.parametrize("document", [["not", "an", "object"], None, "text"])
async def test_a_document_that_is_not_an_object_is_reported_empty(
    respx_mock, adjudicate, document
) -> None:
    _mock_judge(respx_mock, document)

    judgement = await judge_page(adjudicate, PNG, "a", "b")

    assert judgement.document == {}
    assert (judgement.p_b, judgement.p_b_ab, judgement.p_a_ba, judgement.model) == (
        None, None, None, None,
    )


@pytest.mark.asyncio
async def test_an_unavailable_judge_is_raised_as_it_is(respx_mock, adjudicate) -> None:
    respx_mock.post(f"{BASE}/v1/capabilities/document.adjudicate.page:execute").mock(
        return_value=httpx.Response(
            503, json={"status": "failed", "error": {"code": "provider_unavailable", "message": "busy"}}
        )
    )

    with pytest.raises(ToolboxProviderUnavailable):
        await judge_page(adjudicate, PNG, "a", "b")


# --- chain ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_chain_renders_then_judges(respx_mock, pdf, adjudicate) -> None:
    _mock_render(respx_mock)
    route = _mock_judge(respx_mock, {"pB": 0.2, "pB_ab": 0.3, "pA_ba": 0.9, "model": "m"})

    chain = await page_judgement(
        pdf, adjudicate, None, page_number=2, candidate_a="A", candidate_b="B",
        artifact_id=SOURCE_ID,
    )

    assert PNG in route.calls.last.request.content
    assert not _no_cache(route.calls.last.request), "the cache is used by default"
    assert chain.judgement.p_b == pytest.approx(0.2)
    assert [step.capability for step in chain.steps] == ["pdf.render", "document.adjudicate.page"]


@pytest.mark.asyncio
async def test_the_chain_forwards_the_options_of_its_steps(respx_mock, pdf, adjudicate) -> None:
    """``dpi`` and ``max_side`` reach the render, ``prompt`` the judge, and
    ``use_remote_cache`` both (review of #605)."""
    render = _mock_render(respx_mock)
    judge = _mock_judge(respx_mock, {"pB": 0.5})

    chain = await page_judgement(
        pdf, adjudicate, None, page_number=2, candidate_a="A", candidate_b="B",
        artifact_id=SOURCE_ID, prompt="para", dpi=96, max_side=1000, use_remote_cache=False,
    )

    sent = _parameters(render.calls.last.request)
    assert (sent["dpi"], sent["max_side"]) == (96, 1000)
    assert _parameters(judge.calls.last.request)["prompt"] == "para"
    assert _no_cache(render.calls.last.request) and _no_cache(judge.calls.last.request)
    assert chain.page.step.parameters == {"page_number": 2, "dpi": 96, "max_side": 1000}
    assert chain.judgement.step.parameters == {"prompt": "para"}
