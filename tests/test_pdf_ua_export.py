"""PDF/UA export through the Toolbox (document.export.pdf_ua) from the core.

The client itself is tested in ``libs/sdk/tests/clients/test_pdf_ua.py``.
These tests cover how the core builds it from the run's ``ToolboxConfig`` and
the exporter,
which renders PDF/UA only on the Toolbox, with no local fallback
(docs/adr/0003).
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox.clients import ToolboxPdfUaClient
from acessilia_sdk.toolbox.clients.pdf_ua import pandoc_payload
from acessilia_sdk.toolbox.errors import (
    ToolboxCapabilityError,
    ToolboxInvalidInput,
    ToolboxTimeout,
)
from tests.core_config_support import export_config, toolbox_config
from backend.config.settings import settings
from acessilia_core.export import pandoc_exporter
from acessilia_core.toolbox.toolbox_client import ToolboxProviderUnavailable, make_toolbox_client

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
    assert make_toolbox_client(ToolboxPdfUaClient, toolbox_config()).timeout_seconds == 300
    assert make_toolbox_client(ToolboxPdfUaClient, toolbox_config(), timeout_seconds=30).timeout_seconds == 30


def test_same_document_yields_the_same_upload_so_the_toolbox_cache_hits():
    from acessilia_core.export.pandoc_exporter import _ensure_document
    from docstruct.export.pandoc_ast import build_pandoc_ast

    markdown = "# Relatório\n\nParágrafo.\n"
    first, second = (
        build_pandoc_ast(_ensure_document(markdown, title="Relatório", toolbox=toolbox_config())) for _ in range(2)
    )
    # The canonical document carries a random id; the AST embeds it.
    assert first["source_document"]["id"] != second["source_document"]["id"]

    assert pandoc_payload(first) == pandoc_payload(second)
    assert b"source_document" not in pandoc_payload(first)
    assert set(json.loads(pandoc_payload(first))) == {"pandoc-api-version", "meta", "blocks"}


# ── Exporter: Toolbox only ──────────────────────────────────────────────


def _export_pdf_ua(tmp_path: Path, *, enabled: bool = True) -> Path:
    return pandoc_exporter.export_accessible_document(
        "# Relatório\n\nParágrafo.\n",
        tmp_path / "doc.pdf_ua.pdf",
        format_name="pdf_ua",
        title="Relatório",
        export=export_config(toolbox_pdf_ua_enabled=enabled),
        toolbox=toolbox_config(),
    )


def test_exporter_renders_on_the_toolbox(monkeypatch, tmp_path):
    calls = []

    def fake_toolbox(ast, output_path, *, lang, toolbox):
        calls.append((ast, lang))
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )

    output = _export_pdf_ua(tmp_path)

    assert output.read_bytes() == PDF
    (ast, lang), = calls
    assert lang == "pt-BR"
    assert ast["blocks"], "the canonical document reaches the Toolbox as a Pandoc AST"


@pytest.mark.parametrize(
    "error",
    [ToolboxProviderUnavailable("pdf-ua-render offline"), RuntimeError("event loop is closed")],
)
def test_a_toolbox_failure_propagates_without_a_local_fallback(
    monkeypatch, tmp_path, error
):

    def failing_toolbox(ast, output_path, *, lang, toolbox):
        raise error

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", failing_toolbox
    )
    with pytest.raises(type(error), match=str(error)):
        _export_pdf_ua(tmp_path)


def test_the_format_is_unavailable_when_disabled(monkeypatch, tmp_path):

    def toolbox_must_not_run(*args, **kwargs):
        raise AssertionError("Toolbox called although TOOLBOX_PDF_UA_ENABLED=false")

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", toolbox_must_not_run
    )

    with pytest.raises(RuntimeError, match="TOOLBOX_PDF_UA_ENABLED=false"):
        _export_pdf_ua(tmp_path, enabled=False)


def test_exporter_takes_the_language_from_the_document(monkeypatch, tmp_path):
    langs = []

    def fake_toolbox(ast, output_path, *, lang, toolbox):
        langs.append(lang)
        output_path.write_bytes(PDF)
        return {}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )
    document = pandoc_exporter._ensure_document("# Report\n\nParagraph.\n", title="Report", toolbox=toolbox_config())
    document["language"] = "en-US"

    pandoc_exporter.export_accessible_document(
        document, tmp_path / "doc.pdf_ua.pdf", format_name="pdf_ua", title="Report",
        export=export_config(),
        toolbox=toolbox_config(),
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


def test_the_core_has_no_local_pdf_ua_toolchain():
    """The local pandoc + LaTeX path and its template are gone (docs/adr/0003)."""
    for name in (
        "_render_with_pandoc",
        "_pandoc_bin",
        "_render_pdf_ua_with_pandoc",
        "_pdf_ua_engine",
        "_pdf_ua_template_path",
        "_xelatex_bin",
        "_lualatex_bin",
    ):
        assert not hasattr(pandoc_exporter, name), name
    assert not (Path(pandoc_exporter.__file__).parent / "templates" / "pdf_ua.tex").exists()
    tree = ast.parse(Path(pandoc_exporter.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not imported & {"subprocess", "shutil"}


@pytest.mark.respx(base_url=BASE_URL)
def test_sync_wrapper_runs_without_an_event_loop(respx_mock, monkeypatch, tmp_path):
    from acessilia_core.export.pandoc_exporter import toolbox_export_pdf_ua

    monkeypatch.setattr(settings, "toolbox_base_url", BASE_URL)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    respx_mock.post(EXECUTE_URL).mock(return_value=httpx.Response(200, json=envelope()))
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{PDF_ID}").mock(
        return_value=httpx.Response(200, content=PDF)
    )

    document = toolbox_export_pdf_ua(AST, tmp_path / "doc.pdf", toolbox=toolbox_config())

    assert document["artifact_id"] == PDF_ID
    assert (tmp_path / "doc.pdf").read_bytes() == PDF


@pytest.mark.respx(base_url=BASE_URL)
@pytest.mark.parametrize("use_remote_cache", [True, False])
def test_sync_wrapper_forwards_the_remote_cache_setting(
    respx_mock, monkeypatch, tmp_path, use_remote_cache
):
    from acessilia_core.export.pandoc_exporter import toolbox_export_pdf_ua

    monkeypatch.setattr(settings, "toolbox_base_url", BASE_URL)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    execute = respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(200, json=envelope())
    )
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{PDF_ID}").mock(
        return_value=httpx.Response(200, content=PDF)
    )

    toolbox_export_pdf_ua(
        AST, tmp_path / "doc.pdf", toolbox=toolbox_config(use_remote_cache=use_remote_cache)
    )

    body = execute.calls.last.request.content
    assert (b'name="no_cache"' in body) is (not use_remote_cache)


# ── Math the renderer rejects: degrade to text and retry once ───────────


MATH_DOCUMENT = {
    "id": "doc-1",
    "schema_version": "1.0.0",
    "title": "Report",
    "language": "pt-BR",
    "sections": [
        {
            "id": "sec-1",
            "level": 1,
            "title": "Formulas",
            "blocks": [
                {
                    "id": "m-1",
                    "type": "math",
                    "text": "\\chemfig{*6((-SO_2O^-Na^+)-=-=)=-=(-N=N-C(=O-O^-Na^+)-N(-C(-OH)=N)=-=)}",
                }
            ],
            "children": [],
        }
    ],
}


def _ast_has_math(ast: dict) -> bool:
    return any(
        isinstance(inline, dict) and inline.get("t") == "Math"
        for block in ast["blocks"]
        if isinstance(block.get("c"), list)
        for inline in block["c"]
    )


def _export_math_document(tmp_path: Path) -> Path:
    return pandoc_exporter.export_accessible_document(
        MATH_DOCUMENT,
        tmp_path / "doc.pdf_ua.pdf",
        format_name="pdf_ua",
        title="Report",
        export=export_config(),
        toolbox=toolbox_config(),
    )


def test_a_math_rejection_degrades_to_text_and_retries_once(monkeypatch, tmp_path):
    """006.pdf: a chemical structure the vision model classified as a formula
    exports LaTeX its compiler rejects (\\chemfig is an undefined control
    sequence). ToolboxInvalidInput says the renderer is healthy and the AST is
    the problem, so the retry is a deterministic degradation: the formulas go
    as literal text, and one block no longer loses the whole PDF."""
    calls = []

    def fake_toolbox(ast, output_path, *, lang, toolbox):
        calls.append(ast)
        if len(calls) == 1:
            raise ToolboxInvalidInput(
                "PDF/UA renderer rejected the AST: pandoc failed: Undefined control sequence"
            )
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )

    output = _export_math_document(tmp_path)

    assert output.read_bytes() == PDF
    first, second = calls
    assert _ast_has_math(first), "the first attempt keeps the formula as math"
    assert not _ast_has_math(second), "the retry carries no Math inline"
    texts = [
        inline["c"]
        for block in second["blocks"]
        if block.get("t") == "Para"
        for inline in block["c"]
        if isinstance(inline, dict) and inline.get("t") == "Str"
    ]
    assert any("chemfig" in text for text in texts), "the formula source survives as text"


@pytest.mark.parametrize(
    "error",
    [
        ToolboxProviderUnavailable("pdf-ua-render offline"),
        ToolboxTimeout("the export timed out"),
        ToolboxCapabilityError("capability drifted"),
    ],
)
def test_only_an_input_rejection_retries(monkeypatch, tmp_path, error):
    """A healthy renderer rejecting the input retries with degraded math; an
    outage or a contract drift does not — retrying would only add latency."""
    calls = []

    def failing_toolbox(ast, output_path, *, lang, toolbox):
        calls.append(ast)
        raise error

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", failing_toolbox
    )

    with pytest.raises(type(error), match=re.escape(str(error))):
        _export_math_document(tmp_path)

    assert len(calls) == 1


def test_a_second_rejection_propagates(monkeypatch, tmp_path):
    """One retry is the whole contract for a single formula (multi-formula
    documents use bounded bisection): if the degraded AST is rejected too,
    that is a real failure and propagates without logging a false recovery."""
    calls = []
    warnings: list[str] = []

    def failing_toolbox(ast, output_path, *, lang, toolbox):
        calls.append(ast)
        raise ToolboxInvalidInput(f"pandoc failed (attempt {len(calls)})")

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", failing_toolbox
    )
    monkeypatch.setattr(pandoc_exporter.logger, "warning", lambda msg, *a, **kw: warnings.append(str(msg)))

    with pytest.raises(
        ToolboxInvalidInput, match=re.escape("pandoc failed (attempt 2)")
    ):
        _export_math_document(tmp_path)

    assert len(calls) == 2
    assert not warnings


def test_an_ast_without_math_does_not_retry(monkeypatch, tmp_path):
    """ToolboxInvalidInput covers any 400 invalid_input, not only math: when
    the degradation changes nothing, a retry would resend the identical
    request — double the latency of a 42-page render for the same rejection."""
    calls = []

    def failing_toolbox(ast, output_path, *, lang, toolbox):
        calls.append(ast)
        raise ToolboxInvalidInput("pandoc failed")

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", failing_toolbox
    )

    with pytest.raises(ToolboxInvalidInput, match="pandoc failed"):
        pandoc_exporter.export_accessible_document(
            "# Report\n\nParagraph.\n",
            tmp_path / "doc.pdf_ua.pdf",
            format_name="pdf_ua",
            title="Report",
            export=export_config(),
            toolbox=toolbox_config(),
        )

    assert len(calls) == 1


def test_the_format_needs_the_run_export_config(monkeypatch, tmp_path):
    """No fallback to the settings: PDF/UA without an ``ExportConfig`` is a programming error."""

    def toolbox_must_not_run(*args, **kwargs):
        raise AssertionError("the Toolbox ran without an export config")

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", toolbox_must_not_run
    )

    with pytest.raises(TypeError, match="ExportConfig"):
        pandoc_exporter.export_accessible_document(
            "# Report\n", tmp_path / "doc.pdf_ua.pdf", format_name="pdf_ua",
            toolbox=toolbox_config(),
        )


def test_the_format_needs_the_run_toolbox_config(tmp_path):
    """No fallback to the settings: a Toolbox format without a ``ToolboxConfig`` is a programming error."""
    with pytest.raises(TypeError, match="ToolboxConfig"):
        pandoc_exporter.export_accessible_document(
            "# Report\n", tmp_path / "doc.pdf_ua.pdf", format_name="pdf_ua", export=export_config(),
        )


# ── Per-formula PDF/UA degradation (#258) ───────────────────────────────


def _all_math_nodes(node: object) -> list[dict]:
    if isinstance(node, list):
        return [found for item in node for found in _all_math_nodes(item)]
    if isinstance(node, dict):
        if node.get("t") == "Math":
            return [node]
        if "c" in node:
            return _all_math_nodes(node["c"])
        if "blocks" in node:
            return _all_math_nodes(node["blocks"])
    return []


def _all_math_latex(ast_doc: dict) -> list[str]:
    return [str(math["c"][1]) for math in _all_math_nodes(ast_doc["blocks"])]


def _all_formula_span_alts(node: object) -> list[str]:
    if isinstance(node, list):
        return [alt for item in node for alt in _all_formula_span_alts(item)]
    if isinstance(node, dict):
        if node.get("t") == "Span":
            attrs = node["c"][0]
            if len(attrs) > 1 and "accessilia-formula" in (attrs[1] or []):
                return [dict(attrs[2]).get("alt", "")]
        if "c" in node:
            return _all_formula_span_alts(node["c"])
        if "blocks" in node:
            return _all_formula_span_alts(node["blocks"])
    return []


def _multi_formula_doc(
    formulas: list[str],
    *,
    mathml_indices: set[int] | None = None,
    with_alt: bool = False,
) -> dict:
    mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>'
    blocks = []
    for idx, latex in enumerate(formulas):
        block: dict = {"id": f"m-{idx}", "type": "math", "text": latex}
        if with_alt:
            block["alt_text"] = f"Formula {idx}"
        if mathml_indices is not None and idx in mathml_indices:
            block["metadata"] = {"mathml": mathml}
        blocks.append(block)
    return {
        "id": "doc-multi",
        "schema_version": "1.0.0",
        "title": "Report",
        "language": "en-US",
        "sections": [
            {
                "id": "sec-1",
                "level": 1,
                "title": "Formulas",
                "blocks": blocks,
                "children": [],
            }
        ],
    }


def _export_document(
    document: dict,
    tmp_path: Path,
    *,
    bisect_budget: int | None = None,
    check_cancelled=None,
) -> Path:
    export_kwargs = {}
    if bisect_budget is not None:
        export_kwargs["toolbox_pdf_ua_math_bisect_budget"] = bisect_budget
    return pandoc_exporter.export_accessible_document(
        document,
        tmp_path / "doc.pdf_ua.pdf",
        format_name="pdf_ua",
        title="Report",
        export=export_config(**export_kwargs),
        toolbox=toolbox_config(),
        check_cancelled=check_cancelled,
    )


def test_one_bad_formula_keeps_every_other_formula_typeset(monkeypatch, tmp_path):
    """#258 acceptance: a document with one unrenderable formula keeps every
    other formula typeset in the PDF/UA, even without MathML metadata."""
    formulas = [f"x_{i} = {i}" for i in range(6)]
    formulas[4] = r"\chemfig{H-O-H}"
    doc = _multi_formula_doc(formulas, with_alt=True)
    succeeded: list[dict] = []

    def fake_toolbox(ast_doc, output_path, *, lang, toolbox):
        if any(r"\chemfig" in latex for latex in _all_math_latex(ast_doc)):
            raise ToolboxInvalidInput("pandoc failed: Undefined control sequence \\chemfig")
        succeeded.append(ast_doc)
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )

    output = _export_document(doc, tmp_path)

    assert output.read_bytes() == PDF
    final_ast = succeeded[-1]
    assert _all_math_latex(final_ast) == [f"x_{i} = {i}" for i in range(6) if i != 4]
    # Every surviving formula keeps its Formula alternate text; the degraded one does not.
    assert _all_formula_span_alts(final_ast) == [f"Formula {i}" for i in range(6) if i != 4]
    assert "chemfig" in json.dumps(final_ast["blocks"])


def test_one_bad_inline_formula_keeps_display_and_other_inline_math(monkeypatch, tmp_path):
    """Per-formula degradation also isolates a bad inline formula inside prose
    or a table cell without degrading surrounding display or inline math."""
    doc = {
        "id": "doc-inline",
        "schema_version": "1.0.0",
        "title": "Report",
        "language": "en-US",
        "sections": [
            {
                "id": "sec-1",
                "level": 1,
                "title": "Section",
                "blocks": [
                    {
                        "id": "m-1",
                        "type": "math",
                        "text": "E = mc^2",
                        "alt_text": "Formula: E equals m c squared",
                    },
                    {
                        "id": "p-1",
                        "type": "paragraph",
                        "text": r"Here $a+b$ works and $\chemfig{H-O-H}$ fails.",
                    },
                    {
                        "id": "t-1",
                        "type": "table",
                        "table_ast": {
                            "caption": "Values of $x^2$",
                            "body": [{"cells": [{"text": "Result $y = 2x$"}]}],
                        },
                    },
                ],
                "children": [],
            }
        ],
    }
    succeeded: list[dict] = []

    def fake_toolbox(ast_doc, output_path, *, lang, toolbox):
        if any(r"\chemfig" in latex for latex in _all_math_latex(ast_doc)):
            raise ToolboxInvalidInput("Undefined control sequence \\chemfig")
        succeeded.append(ast_doc)
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )

    output = _export_document(doc, tmp_path)

    assert output.read_bytes() == PDF
    final_ast = succeeded[-1]
    assert _all_math_latex(final_ast) == ["E = mc^2", "a+b", "x^2", "y = 2x"]
    assert _all_formula_span_alts(final_ast) == ["Formula: E equals m c squared"]
    assert "chemfig" in json.dumps(final_ast["blocks"])


def test_unconverted_math_suspect_degrades_in_one_retry(monkeypatch, tmp_path):
    """Option 1 (#258): when math.convert converted every formula except the
    offending one, degrading that single suspect succeeds in two total calls."""
    formulas = [f"x_{i} = {i}" for i in range(16)]
    formulas[11] = r"\chemfig{C-C}"
    doc = _multi_formula_doc(formulas, mathml_indices=set(range(16)) - {11})
    rendered: list[dict] = []

    def fake_toolbox(ast_doc, output_path, *, lang, toolbox):
        rendered.append(ast_doc)
        if any(r"\chemfig" in latex for latex in _all_math_latex(ast_doc)):
            raise ToolboxInvalidInput("Undefined control sequence \\chemfig")
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )

    output = _export_document(doc, tmp_path)

    assert output.read_bytes() == PDF
    assert len(rendered) == 2
    assert _all_math_latex(rendered[-1]) == [f"x_{i} = {i}" for i in range(16) if i != 11]


def test_false_mathml_suspect_falls_back_to_bisect_and_keeps_good_formulas(monkeypatch, tmp_path):
    """If the unconverted formula actually compiles and a converted one is what
    LuaLaTeX rejects, bisection still isolates only the real offender."""
    formulas = ["a=1", "b=2", r"\ce{H2O}", "d=4"]
    # Formula 0 lacks MathML (false suspect), while formula 2 is what LuaLaTeX rejects.
    doc = _multi_formula_doc(formulas, mathml_indices={1, 2, 3})
    rendered: list[dict] = []

    def fake_toolbox(ast_doc, output_path, *, lang, toolbox):
        rendered.append(ast_doc)
        if any(r"\ce" in latex for latex in _all_math_latex(ast_doc)):
            raise ToolboxInvalidInput("Undefined control sequence \\ce")
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )

    output = _export_document(doc, tmp_path)

    assert output.read_bytes() == PDF
    assert _all_math_latex(rendered[-1]) == ["a=1", "b=2", "d=4"]


def test_multiple_bad_formulas_in_both_halves_are_isolated(monkeypatch, tmp_path):
    """When offending formulas appear in both halves of the document, bisection
    finds all of them while keeping every good formula typeset."""
    formulas = [r"\chemfig{A}", "x=1", "y=2", r"\ce{B}", "z=3", "w=4"]
    doc = _multi_formula_doc(formulas)
    rendered: list[dict] = []

    def fake_toolbox(ast_doc, output_path, *, lang, toolbox):
        rendered.append(ast_doc)
        latexes = _all_math_latex(ast_doc)
        if any(r"\chemfig" in item or r"\ce" in item for item in latexes):
            raise ToolboxInvalidInput("Undefined control sequence")
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )

    output = _export_document(doc, tmp_path)

    assert output.read_bytes() == PDF
    assert _all_math_latex(rendered[-1]) == ["x=1", "y=2", "z=3", "w=4"]


def test_non_math_rejection_on_multi_formula_document_fails_fast(monkeypatch, tmp_path):
    """When degrading all math still fails, the rejection is not about math:
    bisection stops immediately after verifying all-degraded fails."""
    doc = _multi_formula_doc([f"x_{i} = {i}" for i in range(16)])
    calls: list[dict] = []

    def always_reject(ast_doc, output_path, *, lang, toolbox):
        calls.append(ast_doc)
        raise ToolboxInvalidInput("broken document metadata")

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", always_reject
    )

    with pytest.raises(ToolboxInvalidInput, match="broken document metadata"):
        _export_document(doc, tmp_path)

    # Initial + left half + right half + all degraded = 4 calls regardless of formula count.
    assert len(calls) == 4


def test_bisection_render_count_is_strictly_bounded(monkeypatch, tmp_path):
    """Even when every formula in a large document fails, retries stay strictly
    within ``1 + budget`` total calls (including the all-degraded fallback)."""
    budget = 6
    doc = _multi_formula_doc([rf"\badmacro{{{i}}}" for i in range(20)])
    calls: list[dict] = []
    succeeded: list[dict] = []

    def reject_any_math(ast_doc, output_path, *, lang, toolbox):
        calls.append(ast_doc)
        if _all_math_latex(ast_doc):
            raise ToolboxInvalidInput("Undefined control sequence \\badmacro")
        succeeded.append(ast_doc)
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", reject_any_math
    )

    output = _export_document(doc, tmp_path, bisect_budget=budget)

    assert output.read_bytes() == PDF
    assert len(calls) <= 1 + budget
    assert succeeded and not _all_math_latex(succeeded[-1])


def test_budget_exhaustion_keeps_rescued_formulas_and_logs_distinct_warning(monkeypatch, tmp_path):
    """When the retry budget runs out before isolating every chunk, the final
    PDF comes from the smallest render-verified AST (preserving already-rescued
    good formulas) and logs a budget-exhausted warning rather than claiming
    every degraded formula was individually rejected (#258)."""
    bad_indices = {5, 7, 16, 51}
    formulas = [
        rf"\bad{{{i}}}" if i in bad_indices else f"x_{i} = {i}"
        for i in range(60)
    ]
    doc = _multi_formula_doc(formulas)
    calls: list[dict] = []
    succeeded: list[dict] = []
    warnings: list[str] = []

    def reject_bad(ast_doc, output_path, *, lang, toolbox):
        calls.append(ast_doc)
        if any(r"\bad{" in latex for latex in _all_math_latex(ast_doc)):
            raise ToolboxInvalidInput("Undefined control sequence \\bad")
        succeeded.append(ast_doc)
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", reject_bad
    )
    monkeypatch.setattr(pandoc_exporter.logger, "warning", lambda msg, *a, **kw: warnings.append(str(msg)))

    output = _export_document(doc, tmp_path, bisect_budget=8)

    assert output.read_bytes() == PDF
    assert len(calls) <= 1 + 8
    # The final file on disk was written by a render-verified AST that rescued clean blocks.
    kept = _all_math_latex(succeeded[-1])
    assert len(kept) >= 15
    assert all(r"\bad{" not in latex for latex in kept)
    # Warning clearly reports budget exhaustion instead of overstating rejections.
    assert len(warnings) == 1
    assert "8-render budget" in warnings[0]
    assert "not individually isolated" in warnings[0]


def test_default_bisect_cap_reads_module_constant_dynamically(monkeypatch, tmp_path):
    """Calling ``_render_pdf_ua`` without an explicit cap reads
    ``_MAX_MATH_BISECT_ATTEMPTS`` at call time (not import time)."""
    from docstruct.export.pandoc_ast import build_pandoc_ast

    doc = _multi_formula_doc([rf"\bad{{{i}}}" for i in range(8)])
    ast_doc = build_pandoc_ast(doc, target_format="pdf_ua")
    calls: list[dict] = []

    def reject_any_math(candidate, output_path, *, lang, toolbox):
        calls.append(candidate)
        if _all_math_latex(candidate):
            raise ToolboxInvalidInput("Undefined control sequence \\bad")
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", reject_any_math
    )
    monkeypatch.setattr(pandoc_exporter, "_MAX_MATH_BISECT_ATTEMPTS", 2)

    output = pandoc_exporter._render_pdf_ua(
        ast_doc, tmp_path / "doc.pdf_ua.pdf", enabled=True, toolbox=toolbox_config()
    )

    assert output.read_bytes() == PDF
    assert len(calls) <= 1 + 2


def test_cancellation_aborts_bisection_before_next_retry(monkeypatch, tmp_path):
    """A user cancellation checked between retry renders stops bisection
    immediately instead of holding the worker across the remaining budget."""
    class _Cancelled(Exception):
        pass

    doc = _multi_formula_doc([f"x_{i} = {i}" for i in range(8)])
    calls: list[dict] = []

    def reject_all(ast_doc, output_path, *, lang, toolbox):
        calls.append(ast_doc)
        raise ToolboxInvalidInput("Undefined control sequence")

    def check_cancelled() -> None:
        if len(calls) >= 2:
            raise _Cancelled("job cancelled")

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", reject_all
    )

    with pytest.raises(_Cancelled, match="job cancelled"):
        _export_document(doc, tmp_path, check_cancelled=check_cancelled)

    # Initial attempt + 1 retry before cancellation stopped the second retry.
    assert len(calls) == 2


def test_transient_math_convert_outage_falls_back_to_balanced_split(monkeypatch, tmp_path):
    """When most formulas lack MathML (> half, e.g. transient math.convert outage),
    bisection uses a balanced 50/50 split rather than a skewed suspect probe."""
    formulas = [f"x_{i} = {i}" for i in range(8)]
    formulas[7] = r"\chemfig{A}"
    # Only formula 0 has MathML (7 of 8 unconverted -> > half).
    doc = _multi_formula_doc(formulas, mathml_indices={0})
    calls: list[dict] = []
    succeeded: list[dict] = []

    def fake_toolbox(ast_doc, output_path, *, lang, toolbox):
        calls.append(ast_doc)
        if any(r"\chemfig" in latex for latex in _all_math_latex(ast_doc)):
            raise ToolboxInvalidInput("Undefined control sequence \\chemfig")
        succeeded.append(ast_doc)
        output_path.write_bytes(PDF)
        return {"artifact_id": PDF_ID}

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", fake_toolbox
    )

    output = _export_document(doc, tmp_path)

    assert output.read_bytes() == PDF
    # First retry probed the balanced half (4 kept), not only formula 0 (1 kept).
    assert len(_all_math_latex(calls[1])) == 4
    assert _all_math_latex(succeeded[-1]) == [f"x_{i} = {i}" for i in range(7)]


@pytest.mark.parametrize(("raw", "expected"), [(None, 8), ("4", 4), ("0", 0), ("-3", 0)])
def test_toolbox_pdf_ua_math_bisect_budget_is_parsed_from_env(monkeypatch, raw, expected):
    from backend.config.settings import Settings

    if raw is None:
        monkeypatch.delenv("TOOLBOX_PDF_UA_MATH_BISECT_BUDGET", raising=False)
    else:
        monkeypatch.setenv("TOOLBOX_PDF_UA_MATH_BISECT_BUDGET", raw)
    assert Settings().toolbox_pdf_ua_math_bisect_budget == expected


def test_non_input_error_during_bisection_propagates_immediately(monkeypatch, tmp_path):
    """An outage or timeout during a bisection retry must propagate instead of
    being treated as another formula rejection."""
    doc = _multi_formula_doc(["a=1", r"\chemfig{A}", "b=2", "c=3"])
    calls: list[dict] = []

    def flaky_toolbox(ast_doc, output_path, *, lang, toolbox):
        calls.append(ast_doc)
        if len(calls) == 1:
            raise ToolboxInvalidInput("Undefined control sequence \\chemfig")
        raise ToolboxTimeout("renderer timed out during retry")

    monkeypatch.setattr(
        "acessilia_core.export.pandoc_exporter.toolbox_export_pdf_ua", flaky_toolbox
    )

    with pytest.raises(ToolboxTimeout, match="renderer timed out during retry"):
        _export_document(doc, tmp_path)

    assert len(calls) == 2

