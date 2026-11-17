"""Test-only adapters prove the walker can retain the existing four policies.

Production exporters remain unchanged until E1.7. Delegate serialization and
section-header construction to their existing functions; only traversal is
substituted here. The original E1.0 gate continues to check the frozen files.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from docstruct.export import html, markdown, pandoc_ast, txt
from docstruct.export.walk import Visitor, walk
from docstruct.profiles import filter_blocks_for_profile

ROOT = Path(__file__).resolve().parents[3] / "tests/fixtures/export_snapshots"
SPEC = importlib.util.spec_from_file_location("walker_parity_capture", ROOT / "capture.py")
assert SPEC and SPEC.loader
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)
VARIANTS = list(CAPTURE.variants())


def _section_shell(context):
    legacy = context.legacy_title
    return {**context.data, "blocks": [legacy] if legacy is not None else [], "children": []}


def _flatten(source, visitor, select=None):
    return [item for group in walk({"sections": [source]}, visitor, select) for item in group]


def _substitute_traversal(context, kind):
    if kind == "txt":
        original = txt._render_section

        def render_section(section, profile_name, formula_label=txt.DEFAULT_FORMULA_LABEL):
            return _flatten(section, Visitor(
                default=lambda block, ctx: txt._render_block(
                    block, formula_label if ctx.section.depth == 0 else txt.DEFAULT_FORMULA_LABEL,
                ),
                enter_section=lambda ctx: original(_section_shell(ctx), profile_name, formula_label),
            ), lambda block, ctx: not ctx.is_legacy_title and bool(
                filter_blocks_for_profile([block], profile_name)
            ))

        context.setattr(txt, "_render_section", render_section)
    elif kind == "html":
        original = html._collect_section

        def collect(section):
            return _flatten(section, Visitor(
                default=lambda block, ctx: [block],
                enter_section=lambda ctx: original(_section_shell(ctx)),
            ), lambda block, ctx: not ctx.is_legacy_title)

        context.setattr(html, "_collect_section", collect)
    elif kind == "pandoc":
        original = pandoc_ast._section_to_blocks

        def render_section(section, *, target_format="latex"):
            return _flatten(section, Visitor(
                default=lambda block, ctx: pandoc_ast._block_to_ast(block, target_format=target_format),
                enter_section=lambda ctx: original(_section_shell(ctx), target_format=target_format),
            ), lambda block, ctx: not ctx.is_legacy_title)

        context.setattr(pandoc_ast, "_section_to_blocks", render_section)
    else:
        original = markdown._walk_sections

        def sections(sections):
            return walk({"sections": sections}, Visitor(
                default=lambda block, ctx: markdown._render_block(block) or None,
                enter_section=lambda ctx: next(iter(original([
                    {**ctx.data, "blocks": [], "children": []},
                ])), None),
            ), lambda block, ctx: not (
                block.get("type") == "heading"
                and (ctx.section.data.get("title") or "").strip()
                and (block.get("text") or "").strip() == (ctx.section.data.get("title") or "").strip()
            ))

        context.setattr(markdown, "_walk_sections", sections)


@pytest.mark.parametrize("case,export", VARIANTS, ids=[
    f"{case}-{export['snapshot']}" for case, export in VARIANTS
])
def test_walker_composition_matches_the_characterized_export(case, export, monkeypatch):
    source = json.loads((ROOT / "inputs" / f"{case}.json").read_text("utf-8"))
    before = deepcopy(source)
    expected = CAPTURE.render(source, export)
    with monkeypatch.context() as context:
        _substitute_traversal(context, export["kind"])
        actual = CAPTURE.render(source, export)
    assert actual == expected
    assert source == before and json.dumps(source) == json.dumps(before)
