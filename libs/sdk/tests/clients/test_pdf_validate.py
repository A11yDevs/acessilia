"""Tests for the ToolboxPdfValidateClient (pdf.validate.pdf_ua, veraPDF)."""
from __future__ import annotations

from pathlib import Path

import pytest
import respx

from acessilia_sdk.toolbox import ToolboxContractViolation
from acessilia_sdk.toolbox.capabilities import provider_default
from acessilia_sdk.toolbox.clients import ToolboxPdfValidateClient

URL = "http://localhost:8002/v1/capabilities/pdf.validate.pdf_ua:execute"

REPORT = {
    "compliant": False,
    "profile": "ua1",
    "profile_name": "PDF/UA-1 validation profile",
    "statement": "PDF file is not compliant with Validation Profile requirements.",
    "summary": {"passed_rules": 100, "failed_rules": 1, "passed_checks": 29, "failed_checks": 1},
    "failures": [
        {
            "specification": "ISO 14289-1:2014",
            "clause": "7.1",
            "test_number": 11,
            "description": "StructTreeRoot required",
            "object": "PDDocument",
            "test": "containsStructTreeRoot == true",
            "tags": ["structure"],
            "failed_checks": 1,
            "checks": [{"context": "root/document[0]", "message": "missing"}],
        }
    ],
}


@pytest.fixture
def pdf(tmp_path) -> Path:
    path = tmp_path / "document.pdf_ua.pdf"
    path.write_bytes(b"%PDF-1.7\n% fake\n%%EOF\n")
    return path


@pytest.fixture
def client() -> ToolboxPdfValidateClient:
    return ToolboxPdfValidateClient(base_url="http://localhost:8002", timeout_seconds=30)


def _respond(respx_mock, document):
    return respx_mock.post(URL).mock(
        return_value=respx.MockResponse(
            status_code=200,
            json={
                "status": "succeeded",
                "capability": "pdf.validate.pdf_ua",
                "provider": "verapdf",
                "document": document,
            },
        )
    )


def test_the_default_provider_is_verapdf(client):
    assert client.provider == provider_default("toolbox_pdf_validate_provider") == "verapdf"


@pytest.mark.asyncio
async def test_validate_sends_the_profile_and_returns_the_report(respx_mock, client, pdf):
    route = _respond(respx_mock, REPORT)

    report = await client.validate(file_path=pdf, profile="ua2")

    assert report == REPORT
    content = route.calls.last.request.content
    # Form field "parameters", JSON-encoded by the transport.
    assert b'{"profile": "ua2"}' in content
    assert b"verapdf" in content


@pytest.mark.asyncio
async def test_an_unknown_profile_is_refused_before_any_request(respx_mock, client, pdf):
    route = respx_mock.post(URL)

    with pytest.raises(ValueError, match="profile"):
        await client.validate(file_path=pdf, profile="1b")

    assert not route.called


@pytest.mark.asyncio
async def test_a_response_without_a_verdict_is_a_contract_violation(respx_mock, client, pdf):
    _respond(respx_mock, {"profile": "ua1"})

    with pytest.raises(ToolboxContractViolation, match="validation report"):
        await client.validate(file_path=pdf)
