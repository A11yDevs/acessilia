"""Unicode offsets refer to source text, never guessed Markdown positions."""
import json
from collections import Counter

import pytest

from backend.pipeline.fusion import _canonical_to_diff, _group_by_page
from docstruct.fusion.noise import fuse_line_runs, split_decor
from docstruct.fusion.spans import map_charspans
from scripts.drbench.experiments.differ.lib_fuse import _row_to_diff
from scripts.drbench.experiments.differ.tree_differ_v2 import load_blocks
from scripts.drbench.run_pipeline import provider_blocks


def source(text, spans, **kwargs):
    return {"text": text, "field": "text", "charspans": spans,
            "preserve_controls": False, **kwargs}


def test_unicode_cleanup_and_heading_offsets_are_exact():
    raw = "  Á😀\x00\r\nZ  "
    context = map_charspans(source(raw, [[0, len(raw)], [2, 4], [5, 7], [6, 7]]), "## Á😀\nZ")
    assert context["offset_unit"] == "unicode_codepoint"
    assert context["markdown_scope"] == "source_block"
    assert context["markdown"] == "## Á😀\nZ"
    assert [s["markdown_span"] for s in context["spans"]] == [[3, 7], [3, 5], [5, 6], None]
    assert context["spans"][-1]["status"] == "unmapped_boundary"


@pytest.mark.parametrize("span", [[-1, 2], [0, 9], [2, 1], [True, 2], [0, 1.5], ["0", 2], [0]])
def test_invalid_spans_are_marked_without_coercion_or_clamping(span):
    record = map_charspans(source("Á😀", [span]), "Á😀")["spans"][0]
    assert record["source_span"] == span
    assert record["status"] == "invalid_span"
    assert record["markdown_span"] is None


def test_removed_empty_ambiguous_and_unknown_transformations_abstain():
    assert map_charspans(source(" X ", [[0, 1], [1, 1]]), "X")["spans"][0]["status"] == "removed"
    assert map_charspans(source("X", [[0, 0]]), "X")["spans"][0]["status"] == "empty_span"
    assert map_charspans(source("X", [[0, 1]]), "XX")["spans"][0]["status"] == "unmapped_text"
    assert map_charspans(source("a-b", [[0, 3]]), "ab")["spans"][0]["status"] == "unmapped_text"
    assert map_charspans(source("X", [[0, 1]], field="orig"), "X")["spans"][0]["status"] == "unknown_scope"


def test_formula_wrappers_preserve_offsets_and_repeated_spans():
    context = map_charspans(source("x+😀", [[0, 3], [0, 3]]), "$$x+😀$$")
    assert [s["markdown_span"] for s in context["spans"]] == [[2, 5], [2, 5]]
    code = map_charspans(source("a\x00b", [[0, 3]], preserve_controls=True), "a\x00b")
    assert code["spans"][0]["markdown_span"] == [0, 3]


def test_cli_and_backend_keep_source_snapshots_through_joins_and_splits(tmp_path):
    elements = [{"id": str(i), "type": "paragraph", "text": text, "reading_order": i,
                 "metadata": {"text_source": source(text, [[0, len(text)]])}}
                for i, text in enumerate(["Alpha", "Beta", "Gamma"], 1)]
    payload = {"document": {"elements": elements}}
    blocks = provider_blocks(payload)
    path = tmp_path/'page.blocks.json'; path.write_text(json.dumps(blocks))
    diffs = [_row_to_diff(b) for b in load_blocks(path)]
    backend = [_canonical_to_diff(b) for bs in _group_by_page(payload).values() for b in bs]
    assert [d.text_sources for d in diffs] == [d.text_sources for d in backend]
    assert [d.text_sources[0]["spans"][0]["markdown_span"] for d in diffs] == [[0, 5], [0, 4], [0, 5]]
    for i, d in enumerate(diffs):
        d.box = (0.1, 0.1+i*0.06, 0.5, 0.15+i*0.06)
    joined = fuse_line_runs(diffs, Counter(), "M")
    assert len(joined) == 1
    assert [s["markdown"] for s in joined[0].text_sources] == ["Alpha", "Beta", "Gamma"]
    assert all(s["markdown_scope"] == "source_block" for s in joined[0].text_sources)
    assert all(s["markdown"] != joined[0].md for s in joined[0].text_sources)
    footer = backend[0].copy(); footer.md = "Footer text 12"; footer.text = footer.md; footer.type = "page_footer"
    _, decor = split_decor([footer], Counter(), "M")
    assert len(decor) == 2
    assert all(d.text_sources == footer.text_sources for d in decor)


def test_legacy_blocks_do_not_infer_offsets(tmp_path):
    path = tmp_path/'legacy.blocks.json'
    path.write_text(json.dumps([{"type": "paragraph", "text": "X", "markdown": "X"}]))
    assert _row_to_diff(load_blocks(path)[0]).text_sources == ()
