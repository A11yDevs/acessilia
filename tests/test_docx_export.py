"""DOCX export through the Toolbox (document.export.docx) from the core.

The client itself is tested in ``libs/sdk/tests/clients/test_docx.py``.
These tests cover how the core builds it from ``settings`` and the exporter,
which renders DOCX only on the Toolbox, with no local fallback
(docs/adr/0003).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox.clients import ToolboxDocxClient
from acessilia_sdk.toolbox.clients.docx import DOCX_MEDIA_TYPE
from backend.config.settings import settings
from backend.export import pandoc_exporter
from backend.tools.toolbox_client import ToolboxProviderUnavailable, make_toolbox_client

BASE_URL = "http://localhost:8002"
EXECUTE_URL = f"{BASE_URL}/v1/capabilities/document.export.docx:execute"
DOCX = b"PK\x03\x04 a docx archive"
DOCX_ID = "sha256:" + hashlib.sha256(DOCX).hexdigest()
AST = {
    "pandoc-api-version": [1, 23, 1],
    "meta": {},
    "blocks": [{"t": "Para", "c": [{"t": "Str", "c": "Olá"}]}],
}


def _export_docx(tmp_path: Path, document: str | dict = "# Relatório\n\nParágrafo.\n") -> Path:
    return pandoc_exporter.export_accessible_document(
        document, tmp_path / "doc.docx", format_name="docx", title="Relatório"
    )


def test_client_uses_the_docx_timeout_and_provider(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_timeout_seconds", 3600)
    monkeypatch.setattr(settings, "toolbox_docx_timeout_seconds", 240)
    monkeypatch.setattr(settings, "toolbox_docx_provider", "pandoc-docx")
    client = make_toolbox_client(ToolboxDocxClient)
    assert client.timeout_seconds == 240
    assert client.provider == "pandoc-docx"


def test_exporter_renders_on_the_toolbox_in_the_document_language(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_docx_enabled", True)
    calls = []

    def fake_toolbox(ast, output_path, *, lang):
        calls.append((ast, lang))
        output_path.write_bytes(DOCX)
        return {"artifact_id": DOCX_ID}

    monkeypatch.setattr("backend.export.pandoc_exporter.toolbox_export_docx", fake_toolbox)
    document = pandoc_exporter._ensure_document("# Report\n\nParagraph.\n", title="Report")
    document["language"] = "en-US"

    output = _export_docx(tmp_path, document)

    assert output.read_bytes() == DOCX
    (ast, lang), = calls
    assert lang == "en-US"
    assert ast["blocks"], "the canonical document reaches the Toolbox as a Pandoc AST"


def test_a_toolbox_failure_propagates_without_a_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_docx_enabled", True)

    def toolbox_down(ast, output_path, *, lang):
        raise ToolboxProviderUnavailable("pdf-ua-render offline")

    monkeypatch.setattr("backend.export.pandoc_exporter.toolbox_export_docx", toolbox_down)

    with pytest.raises(ToolboxProviderUnavailable, match="offline"):
        _export_docx(tmp_path)
    assert not (tmp_path / "doc.docx").exists()


def test_the_format_is_unavailable_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_docx_enabled", False)

    def toolbox_must_not_run(*args, **kwargs):
        raise AssertionError("the Toolbox ran while DOCX is disabled")

    monkeypatch.setattr(
        "backend.export.pandoc_exporter.toolbox_export_docx", toolbox_must_not_run
    )

    with pytest.raises(RuntimeError, match="TOOLBOX_DOCX_ENABLED=false"):
        _export_docx(tmp_path)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, True), ("true", True), ("SIM", True), ("false", False), ("0", False)],
)
def test_toolbox_docx_enabled_is_parsed_from_the_environment(monkeypatch, raw, expected):
    from backend.config.settings import Settings

    if raw is None:
        monkeypatch.delenv("TOOLBOX_DOCX_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TOOLBOX_DOCX_ENABLED", raw)
    assert Settings().toolbox_docx_enabled is expected


def test_the_python_docx_renderer_is_gone():
    renderers = Path(pandoc_exporter.__file__).parent / "renderers"
    assert not (renderers / "docx_renderer.py").exists()


@pytest.mark.respx(base_url=BASE_URL)
def test_sync_wrapper_downloads_the_stored_docx(respx_mock, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_base_url", BASE_URL)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_api_key", "")
    execute = respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "succeeded",
                "document": {
                    "artifact_id": DOCX_ID,
                    "media_type": DOCX_MEDIA_TYPE,
                    "size_bytes": len(DOCX),
                    "toolchain": {"pandoc": "3.9.0.2"},
                },
                "provenance": {"cache_hit": False, "duration_ms": 30},
            },
        )
    )
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{DOCX_ID}").mock(
        return_value=httpx.Response(200, content=DOCX)
    )

    document = pandoc_exporter.toolbox_export_docx(AST, tmp_path / "doc.docx", lang="pt-BR")

    assert document["artifact_id"] == DOCX_ID
    assert (tmp_path / "doc.docx").read_bytes() == DOCX
    assert b"pandoc-docx" in execute.calls.last.request.content
