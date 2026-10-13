"""Testes para os clientes Toolbox das capacidades da PR #125.

Usa respostas HTTPX mockadas para validar URLs, parâmetros, timeout e parsing
de erro. Cobre document.ocr.page, document.adjudicate.page,
document.adjudicate.region e document.orientation.detect.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from backend.tools.toolbox_adjudicate_client import ToolboxAdjudicateClient
from backend.tools.toolbox_client import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
)
from backend.tools.toolbox_orientation_client import ToolboxOrientationClient
from backend.tools.toolbox_page_ocr_client import ToolboxPageOcrClient

FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"

PAGE_OCR_RESPONSE = {
    "status": "succeeded",
    "capability": "document.ocr.page",
    "provider": "qwen3-vl-page",
    "document": {
        "markdown": "# Title\n\nBody text.",
        "finish": "stop",
        "language": "pt-BR",
    },
}

ADJUDICATE_PAGE_RESPONSE = {
    "status": "succeeded",
    "capability": "document.adjudicate.page",
    "provider": "qwen3-vl-judge",
    "document": {"pB_ab": 0.9, "pA_ba": 0.1, "pB": 0.9},
}

ADJUDICATE_REGION_RESPONSE = {
    "status": "succeeded",
    "capability": "document.adjudicate.region",
    "provider": "qwen3-vl-judge",
    "document": {"text": "exact transcription"},
}

ORIENTATION_RESPONSE = {
    "status": "succeeded",
    "capability": "document.orientation.detect",
    "provider": "rapidocr-orientation",
    "document": {"angle": 90, "tall_frac": 0.8, "n_boxes": 12},
}


@pytest.fixture
def page_ocr() -> ToolboxPageOcrClient:
    return ToolboxPageOcrClient(
        base_url="http://localhost:8002", provider="qwen3-vl-page", timeout_seconds=30
    )


@pytest.fixture
def adjudicate() -> ToolboxAdjudicateClient:
    return ToolboxAdjudicateClient(
        base_url="http://localhost:8002", provider="qwen3-vl-judge", timeout_seconds=30
    )


@pytest.fixture
def orientation() -> ToolboxOrientationClient:
    return ToolboxOrientationClient(
        base_url="http://localhost:8002",
        provider="rapidocr-orientation",
        timeout_seconds=30,
    )


# ---------------------------------------------------------------------------
# document.ocr.page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_ocr_direct_upload(respx_mock, page_ocr):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr.page:execute"
    )
    route.return_value = httpx.Response(200, json=PAGE_OCR_RESPONSE)

    result = await page_ocr.transcribe(file_path=FIXTURE_IMAGE)

    assert result["status"] == "succeeded"
    assert result["document"]["finish"] == "stop"


@pytest.mark.asyncio
async def test_page_ocr_by_artifact_id(respx_mock, page_ocr):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr.page:execute"
    )
    route.return_value = httpx.Response(200, json=PAGE_OCR_RESPONSE)

    result = await page_ocr.transcribe(artifact_id="sha256:abc123")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_page_ocr_raises_on_no_input(page_ocr):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await page_ocr.transcribe()


@pytest.mark.asyncio
async def test_page_ocr_raises_on_failed_status(respx_mock, page_ocr):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr.page:execute"
    )
    route.return_value = httpx.Response(200, json={"status": "failed"})

    with pytest.raises(ToolboxContractViolation):
        await page_ocr.transcribe(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
async def test_page_ocr_raises_on_timeout(respx_mock, page_ocr):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr.page:execute"
    )
    route.side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(ToolboxTimeout):
        await page_ocr.transcribe(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
async def test_page_ocr_raises_on_unavailable(respx_mock, page_ocr):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr.page:execute"
    )
    route.side_effect = httpx.ConnectError("refused")

    with pytest.raises(ToolboxProviderUnavailable):
        await page_ocr.transcribe(file_path=FIXTURE_IMAGE)


# ---------------------------------------------------------------------------
# document.adjudicate.page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adjudicate_page_direct_upload(respx_mock, adjudicate):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.adjudicate.page:execute"
    )
    route.return_value = httpx.Response(200, json=ADJUDICATE_PAGE_RESPONSE)

    result = await adjudicate.judge_page("candidate a", "candidate b", file_path=FIXTURE_IMAGE)

    assert result["status"] == "succeeded"
    assert result["document"]["pB"] == 0.9


@pytest.mark.asyncio
async def test_adjudicate_page_by_artifact_id(respx_mock, adjudicate):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.adjudicate.page:execute"
    )
    route.return_value = httpx.Response(200, json=ADJUDICATE_PAGE_RESPONSE)

    result = await adjudicate.judge_page("a", "b", artifact_id="sha256:abc123")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_adjudicate_page_raises_on_no_input(adjudicate):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await adjudicate.judge_page("a", "b")


@pytest.mark.asyncio
async def test_adjudicate_page_raises_on_failed_status(respx_mock, adjudicate):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.adjudicate.page:execute"
    )
    route.return_value = httpx.Response(200, json={"status": "failed"})

    with pytest.raises(ToolboxContractViolation):
        await adjudicate.judge_page("a", "b", file_path=FIXTURE_IMAGE)


# ---------------------------------------------------------------------------
# document.adjudicate.region
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adjudicate_region_direct_upload(respx_mock, adjudicate):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.adjudicate.region:execute"
    )
    route.return_value = httpx.Response(200, json=ADJUDICATE_REGION_RESPONSE)

    result = await adjudicate.transcribe_region(["hint a", "hint b"], file_path=FIXTURE_IMAGE)

    assert result["status"] == "succeeded"
    assert result["document"]["text"] == "exact transcription"


@pytest.mark.asyncio
async def test_adjudicate_region_raises_on_no_input(adjudicate):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await adjudicate.transcribe_region(["a"])


# ---------------------------------------------------------------------------
# document.orientation.detect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orientation_direct_upload(respx_mock, orientation):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.orientation.detect:execute"
    )
    route.return_value = httpx.Response(200, json=ORIENTATION_RESPONSE)

    result = await orientation.detect(file_path=FIXTURE_IMAGE)

    assert result["status"] == "succeeded"
    assert result["document"]["angle"] == 90


@pytest.mark.asyncio
async def test_orientation_by_artifact_id(respx_mock, orientation):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.orientation.detect:execute"
    )
    route.return_value = httpx.Response(200, json=ORIENTATION_RESPONSE)

    result = await orientation.detect(artifact_id="sha256:abc123")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_orientation_raises_on_no_input(orientation):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await orientation.detect()


@pytest.mark.asyncio
async def test_orientation_raises_on_failed_status(respx_mock, orientation):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.orientation.detect:execute"
    )
    route.return_value = httpx.Response(200, json={"status": "failed"})

    with pytest.raises(ToolboxContractViolation):
        await orientation.detect(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
async def test_orientation_raises_on_timeout(respx_mock, orientation):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.orientation.detect:execute"
    )
    route.side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(ToolboxTimeout):
        await orientation.detect(file_path=FIXTURE_IMAGE)
