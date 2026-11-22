"""E1.7: production exporters compose the shared walker and typed callbacks.

The unchanged E1.0 characterization suite checks all 30 calls against frozen
outputs. This suite checks that those same calls actually use the walker's
per-type/default dispatch, instead of retaining a private dispatch or traversal.
"""

import importlib.util
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from docstruct.export import html, markdown, pandoc_ast, txt
from docstruct.export.walk import BLOCK_TYPES, walk

ROOT = Path(__file__).resolve().parents[3] / "tests/fixtures/export_snapshots"
SPEC = importlib.util.spec_from_file_location("walker_parity_capture", ROOT / "capture.py")
assert SPEC and SPEC.loader
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)
VARIANTS = list(CAPTURE.variants())
MODULES = {"txt": txt, "html": html, "pandoc": pandoc_ast, "markdown": markdown}


@pytest.mark.parametrize("case,export", VARIANTS, ids=[
    f"{case}-{export['snapshot']}" for case, export in VARIANTS
])
def test_characterized_export_uses_shared_traversal_and_typed_dispatch(case, export, monkeypatch):
    source = json.loads((ROOT / "inputs" / f"{case}.json").read_text("utf-8"))
    before = deepcopy(source)
    visitors = []
    dispatched = []

    def observe(document, visitor, select=None):
        # HTML first collects blocks, then applies its global filter before
        # rendering. Only the rendering visitor has all eleven callbacks.
        renders = all(callable(getattr(visitor, kind)) for kind in BLOCK_TYPES)
        visitors.append(renders)
        if renders:
            def record(name, callback):
                def invoke(block, ctx):
                    kind = block.get("type")
                    assert name == (kind if kind in BLOCK_TYPES else "default")
                    assert ctx.section.data["blocks"][ctx.index] is block
                    dispatched.append(name)
                    return callback(block, ctx)
                return invoke

            visitor = replace(visitor, **{
                name: record(name, getattr(visitor, name)) for name in (*BLOCK_TYPES, "default")
            })
        yield from walk(document, visitor, select)

    monkeypatch.setattr(MODULES[export["kind"]], "walk", observe)
    CAPTURE.render(source, export)
    assert any(visitors), "the exporter bypassed the typed rendering visitor"
    if case == "unknown":
        assert "default" in dispatched
    assert source == before and json.dumps(source) == json.dumps(before)


@pytest.mark.parametrize("kind", [[], {}])
@pytest.mark.parametrize("render", [txt.document_to_txt_lines, html.document_to_html, pandoc_ast.build_pandoc_ast])
def test_migration_preserves_type_errors_for_unhashable_block_kinds(kind, render):
    source = {"sections": [{"blocks": [{"type": kind, "text": "Fallback"}]}]}
    before = deepcopy(source)
    with pytest.raises(TypeError, match="unhashable type"):
        render(source)
    assert source == before


@pytest.mark.parametrize("kind", [[], {}])
def test_markdown_keeps_accepting_unhashable_block_kinds_through_fallback(kind):
    source = {"sections": [{"blocks": [{"type": kind, "text": "Fallback"}]}]}
    assert markdown.document_to_markdown(source) == "Fallback\n"


@pytest.mark.parametrize("kind", [[], {}])
@pytest.mark.parametrize("render", [txt.document_to_txt_lines, html.document_to_html])
def test_filtered_unhashable_kinds_do_not_start_failing_validation(kind, render):
    source = {"sections": [{"blocks": [
        {"type": kind, "text": "FILTERED", "verbosity": "technical"},
        {"type": "paragraph", "text": "Kept"},
    ]}]}
    output = render(source, profile="txt")
    assert "Kept" in output and "FILTERED" not in output
