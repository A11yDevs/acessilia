"""ToolboxPdfUaClient: execution, artifact download and hash check."""
from __future__ import annotations

import hashlib

import httpx
import pytest

from acessilia_sdk.toolbox import ToolboxContractViolation, ToolboxProviderUnavailable
from acessilia_sdk.toolbox.clients.pdf_ua import ToolboxPdfUaClient, pandoc_payload

BASE_URL = "http://localhost:8002"
EXECUTE_URL = f"{BASE_URL}/v1/capabilities/document.export.pdf_ua:execute"
PDF = b"%PDF-1.7\n% tagged\n%%EOF\n"
PDF_ID = "sha256:" + hashlib.sha256(PDF).hexdigest()
AST = {
    "pandoc-api-version": [1, 23, 1],
    "meta": {},
    "blocks": [{"t": "Para", "c": [{"t": "Str", "c": "Olá"}]}],
}


def envelope(artifact_id: str = PDF_ID, **document_overrides) -> dict:
    document = {
        "artifact_id": artifact_id,
        "media_type": "application/pdf",
        "size_bytes": len(PDF),
        "pdf_standard": "ua-1",
        "engine": "lualatex",
        "toolchain": {"latex_kernel": "2025-11-01 pl0"},
        **document_overrides,
    }
    return {
        "status": "succeeded",
        "capability": "document.export.pdf_ua@1",
        "provider": "pandoc-pdf-ua",
        "document": document,
        "artifacts": [{"artifact_id": artifact_id, "media_type": "application/pdf", "size": len(PDF)}],
        "provenance": {"cache_hit": True, "duration_ms": 12},
    }


@pytest.fixture
def client() -> ToolboxPdfUaClient:
    return ToolboxPdfUaClient(base_url=BASE_URL, provider="pandoc-pdf-ua", timeout_seconds=30)


@pytest.mark.asyncio
async def test_export_sends_the_ast_and_downloads_the_stored_pdf(respx_mock, client, tmp_path):
    execute = respx_mock.post(EXECUTE_URL).mock(return_value=httpx.Response(200, json=envelope()))
    download = respx_mock.get(f"{BASE_URL}/v1/artifacts/{PDF_ID}").mock(
        return_value=httpx.Response(200, content=PDF)
    )
    output = tmp_path / "doc.pdf_ua.pdf"

    result = await client.export(AST, output, lang="pt-BR")

    assert output.read_bytes() == PDF
    assert result["document"]["artifact_id"] == PDF_ID
    assert result["provenance"]["cache_hit"] is True
    assert execute.called and download.called
    body = execute.calls.last.request.content
    assert b"application/json" in body
    assert pandoc_payload(AST) in body
    assert b'filename="document.ast.json"' in body
    assert b'{"lang": "pt-BR"}' in body
    assert b"pandoc-pdf-ua" in body
    assert not list(tmp_path.glob(".*.part"))


@pytest.mark.asyncio
async def test_export_rejects_a_download_whose_hash_does_not_match(respx_mock, client, tmp_path):
    respx_mock.post(EXECUTE_URL).mock(return_value=httpx.Response(200, json=envelope()))
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{PDF_ID}").mock(
        return_value=httpx.Response(200, content=PDF[:-3])
    )
    output = tmp_path / "doc.pdf"

    with pytest.raises(ToolboxContractViolation, match="does not match"):
        await client.export(AST, output)
    assert not output.exists()


@pytest.mark.asyncio
async def test_export_requires_the_pdf_artifact_id(respx_mock, client, tmp_path):
    respx_mock.post(EXECUTE_URL).mock(return_value=httpx.Response(200, json=envelope(artifact_id="")))
    with pytest.raises(ToolboxContractViolation, match="artifact_id"):
        await client.export(AST, tmp_path / "doc.pdf")


@pytest.mark.asyncio
async def test_export_rejects_a_non_pdf_result(respx_mock, client, tmp_path):
    respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(200, json=envelope(media_type="image/png"))
    )
    with pytest.raises(ToolboxContractViolation, match="expected PDF"):
        await client.export(AST, tmp_path / "doc.pdf")


@pytest.mark.asyncio
async def test_unavailable_renderer_maps_to_provider_unavailable(respx_mock, client, tmp_path):
    respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(503, json={"detail": "pdf-ua-render is not reachable"})
    )
    with pytest.raises(ToolboxProviderUnavailable):
        await client.export(AST, tmp_path / "doc.pdf")


@pytest.mark.asyncio
async def test_export_rejects_a_malformed_artifact_id_before_downloading(respx_mock, client, tmp_path):
    respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(200, json=envelope(artifact_id="../../admin"))
    )
    with pytest.raises(ToolboxContractViolation, match="Malformed Toolbox artifact_id"):
        await client.export(AST, tmp_path / "doc.pdf")
    assert len(respx_mock.calls) == 1, "nothing is fetched for a malformed id"


def test_payload_keeps_only_the_keys_pandoc_reads():
    ast = {**AST, "source_document": {"id": "random"}}
    assert pandoc_payload(ast) == pandoc_payload(AST)
    assert b"source_document" not in pandoc_payload(ast)
