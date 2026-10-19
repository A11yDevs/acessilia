"""ToolboxDocxClient: execution, artifact download and checks of the result.

The shared export flow is covered in depth by ``test_pdf_ua.py``; these tests
pin what differs for DOCX: the capability, the provider, the media type and
the ZIP signature.
"""
from __future__ import annotations

import hashlib

import httpx
import pytest

from acessilia_sdk.toolbox import ToolboxContractViolation
from acessilia_sdk.toolbox.clients.docx import DOCX_MEDIA_TYPE, ToolboxDocxClient
from acessilia_sdk.toolbox.clients.pandoc_export import pandoc_payload

BASE_URL = "http://localhost:8002"
EXECUTE_URL = f"{BASE_URL}/v1/capabilities/document.export.docx:execute"
DOCX = b"PK\x03\x04 a docx archive"
DOCX_ID = "sha256:" + hashlib.sha256(DOCX).hexdigest()
AST = {
    "pandoc-api-version": [1, 23, 1],
    "meta": {},
    "blocks": [{"t": "Para", "c": [{"t": "Str", "c": "Olá"}]}],
}


def envelope(artifact_id: str = DOCX_ID, **document_overrides) -> dict:
    document = {
        "artifact_id": artifact_id,
        "media_type": DOCX_MEDIA_TYPE,
        "size_bytes": len(DOCX),
        "toolchain": {"version": "1.1.0", "pandoc": "3.9.0.2"},
        **document_overrides,
    }
    return {
        "status": "succeeded",
        "capability": "document.export.docx@1",
        "provider": "pandoc-docx",
        "document": document,
        "artifacts": [{"artifact_id": artifact_id, "media_type": DOCX_MEDIA_TYPE, "size": len(DOCX)}],
        "provenance": {"cache_hit": False, "duration_ms": 40},
    }


@pytest.fixture
def client() -> ToolboxDocxClient:
    return ToolboxDocxClient(base_url=BASE_URL, timeout_seconds=30)


def test_the_default_provider_is_pandoc_docx(client):
    assert client.provider == "pandoc-docx"


@pytest.mark.asyncio
async def test_export_sends_the_ast_and_downloads_the_stored_docx(respx_mock, client, tmp_path):
    execute = respx_mock.post(EXECUTE_URL).mock(return_value=httpx.Response(200, json=envelope()))
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{DOCX_ID}").mock(
        return_value=httpx.Response(200, content=DOCX)
    )
    output = tmp_path / "doc.docx"

    result = await client.export(AST, output, lang="en-US")

    assert output.read_bytes() == DOCX
    assert result["document"]["artifact_id"] == DOCX_ID
    body = execute.calls.last.request.content
    assert pandoc_payload(AST) in body
    assert b'{"lang": "en-US"}' in body
    assert b"pandoc-docx" in body


@pytest.mark.asyncio
async def test_export_rejects_a_non_docx_result(respx_mock, client, tmp_path):
    respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(200, json=envelope(media_type="application/pdf"))
    )
    with pytest.raises(ToolboxContractViolation, match="expected DOCX"):
        await client.export(AST, tmp_path / "doc.docx")


@pytest.mark.asyncio
async def test_export_rejects_a_download_that_is_not_a_zip(respx_mock, client, tmp_path):
    pdf = b"%PDF-1.7"
    pdf_id = "sha256:" + hashlib.sha256(pdf).hexdigest()
    respx_mock.post(EXECUTE_URL).mock(return_value=httpx.Response(200, json=envelope(pdf_id)))
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{pdf_id}").mock(
        return_value=httpx.Response(200, content=pdf)
    )
    output = tmp_path / "doc.docx"

    with pytest.raises(ToolboxContractViolation):
        await client.export(AST, output)
    assert not output.exists()
