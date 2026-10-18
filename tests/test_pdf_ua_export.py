"""PDF/UA export through the Toolbox (document.export.pdf_ua) from the core.

The client itself is tested in ``libs/sdk/tests/clients/test_pdf_ua.py``.
These tests cover how the core builds it from ``settings`` and the exporter,
which tries the Toolbox first and still uses local pandoc + LaTeX as the
fallback until #150 removes it (docs/adr/0003).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox.clients import ToolboxPdfUaClient
from acessilia_sdk.toolbox.clients.pdf_ua import pandoc_payload
from backend.config.settings import settings
from backend.export import pandoc_exporter
from backend.tools.toolbox_client import ToolboxProviderUnavailable, make_toolbox_client

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


def test_client_uses_the_pdf_ua_timeout_not_the_shared_one(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_timeout_seconds", 3600)
    monkeypatch.setattr(settings, "toolbox_pdf_ua_timeout_seconds", 300)
    assert make_toolbox_client(ToolboxPdfUaClient).timeout_seconds == 300
    assert make_toolbox_client(ToolboxPdfUaClient, timeout_seconds=30).timeout_seconds == 30


def test_same_document_yields_the_same_upload_so_the_toolbox_cache_hits():
    from backend.export.pandoc_exporter import _ensure_document
    from backend.pipeline.pandoc_ast_builder import build_pandoc_ast

    markdown = "# Relatório\n\nParágrafo.\n"
    first, second = (
        build_pandoc_ast(_ensure_document(markdown, title="Relatório")) for _ in range(2)
    )
    # The canonical document carries a random id; the AST embeds it.
    assert first["source_document"]["id"] != second["source_document"]["id"]

    assert pandoc_payload(first) == pandoc_payload(second)
    assert b"source_document" not in pandoc_payload(first)
    assert set(json.loads(pandoc_payload(first))) == {"pandoc-api-version", "meta", "blocks"}


# ── Exporter: Toolbox first, local fallback ─────────────────────────────


def _export_pdf_ua(tmp_path: Path) -> Path:
    return pandoc_exporter.export_accessible_document(
        "# Relatório\n\nParágrafo.\n",
        tmp_path / "doc.pdf_ua.pdf",
        format_name="pdf_ua",
        title="Relatório",
    )


def test_exporter_uses_the_toolbox_and_skips_local_latex(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", True)
    calls = []

    def fake_toolbox(ast, output_path, *, lang):
        calls.append((ast, lang))
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    def local_must_not_run(*args, **kwargs):
        raise AssertionError("local LaTeX ran although the Toolbox succeeded")

    monkeypatch.setattr(
        "backend.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )
    monkeypatch.setattr(pandoc_exporter, "_render_pdf_ua_with_pandoc", local_must_not_run)

    output = _export_pdf_ua(tmp_path)

    assert output.read_bytes() == PDF
    (ast, lang), = calls
    assert lang == "pt-BR"
    assert ast["blocks"], "the canonical document reaches the Toolbox as a Pandoc AST"


def test_exporter_falls_back_to_local_latex_when_the_toolbox_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", True)

    def failing_toolbox(ast, output_path, *, lang):
        raise ToolboxProviderUnavailable("pdf-ua-render offline")

    def local(ast, output_path, *, lang):
        output_path.write_bytes(b"%PDF-local")
        return output_path

    monkeypatch.setattr(
        "backend.export.pandoc_exporter.toolbox_export_pdf_ua", failing_toolbox
    )
    monkeypatch.setattr(pandoc_exporter, "_render_pdf_ua_with_pandoc", local)

    assert _export_pdf_ua(tmp_path).read_bytes() == b"%PDF-local"


def test_exporter_falls_back_on_an_unexpected_toolbox_error(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", True)

    def broken_toolbox(ast, output_path, *, lang):
        raise RuntimeError("event loop is closed")

    def local(ast, output_path, *, lang):
        output_path.write_bytes(b"%PDF-local")
        return output_path

    monkeypatch.setattr(
        "backend.export.pandoc_exporter.toolbox_export_pdf_ua", broken_toolbox
    )
    monkeypatch.setattr(pandoc_exporter, "_render_pdf_ua_with_pandoc", local)

    assert _export_pdf_ua(tmp_path).read_bytes() == b"%PDF-local"


def test_exporter_takes_the_language_from_the_document(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", False)
    langs = []

    def local(ast, output_path, *, lang):
        langs.append(lang)
        output_path.write_bytes(b"%PDF-local")
        return output_path

    monkeypatch.setattr(pandoc_exporter, "_render_pdf_ua_with_pandoc", local)
    document = pandoc_exporter._ensure_document("# Report\n\nParagraph.\n", title="Report")
    document["language"] = "en-US"

    pandoc_exporter.export_accessible_document(
        document, tmp_path / "doc.pdf_ua.pdf", format_name="pdf_ua", title="Report"
    )

    assert langs == ["en-US"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, True), ("true", True), ("SIM", True), ("1", True), ("false", False), ("0", False), ("no", False)],
)
def test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment(monkeypatch, raw, expected):
    from backend.config.settings import Settings

    if raw is None:
        monkeypatch.delenv("TOOLBOX_PDF_UA_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TOOLBOX_PDF_UA_ENABLED", raw)
    assert Settings().toolbox_pdf_ua_enabled is expected


def test_exporter_reports_both_causes_when_toolbox_and_local_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", True)

    def failing_toolbox(ast, output_path, *, lang):
        raise ToolboxProviderUnavailable("pdf-ua-render offline")

    def failing_local(ast, output_path, *, lang):
        raise RuntimeError("Undefined control sequence")

    monkeypatch.setattr(
        "backend.export.pandoc_exporter.toolbox_export_pdf_ua", failing_toolbox
    )
    monkeypatch.setattr(pandoc_exporter, "_render_pdf_ua_with_pandoc", failing_local)

    with pytest.raises(RuntimeError) as excinfo:
        _export_pdf_ua(tmp_path)
    message = str(excinfo.value)
    assert "pdf-ua-render offline" in message
    assert "Undefined control sequence" in message


def test_exporter_skips_the_toolbox_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", False)

    def toolbox_must_not_run(*args, **kwargs):
        raise AssertionError("Toolbox called although TOOLBOX_PDF_UA_ENABLED=false")

    def local(ast, output_path, *, lang):
        output_path.write_bytes(b"%PDF-local")
        return output_path

    monkeypatch.setattr(
        "backend.export.pandoc_exporter.toolbox_export_pdf_ua", toolbox_must_not_run
    )
    monkeypatch.setattr(pandoc_exporter, "_render_pdf_ua_with_pandoc", local)

    assert _export_pdf_ua(tmp_path).read_bytes() == b"%PDF-local"


@pytest.mark.respx(base_url=BASE_URL)
def test_sync_wrapper_runs_without_an_event_loop(respx_mock, monkeypatch, tmp_path):
    from backend.export.pandoc_exporter import toolbox_export_pdf_ua

    monkeypatch.setattr(settings, "toolbox_base_url", BASE_URL)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    respx_mock.post(EXECUTE_URL).mock(return_value=httpx.Response(200, json=envelope()))
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{PDF_ID}").mock(
        return_value=httpx.Response(200, content=PDF)
    )

    document = toolbox_export_pdf_ua(AST, tmp_path / "doc.pdf")

    assert document["artifact_id"] == PDF_ID
    assert (tmp_path / "doc.pdf").read_bytes() == PDF
