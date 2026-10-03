"""Persisted blocks must retain provider order evidence up to the library."""
import json
from collections import Counter

from docstruct.fusion.convert import block_to_diff
from docstruct.fusion.noise import fuse_line_runs, group_split_blocks, split_decor
from docstruct.fusion.types import DiffBlock
from docstruct.types import CanonicalBlock
from scripts.drbench.experiments.differ.lib_fuse import _row_to_diff
from scripts.drbench.experiments.differ.tree_differ_v2 import load_blocks
from scripts.drbench.run_pipeline import provider_blocks


def test_manifest_to_persisted_blocks_to_diff_preserves_native_index_and_absence(tmp_path):
    contexts = [
        {"provider": "mineru", "source": "preproc_blocks.index", "page_idx": 0, "native_index": 8},
        {"provider": "mineru", "source": "collection", "page_idx": 0, "native_index": None},
    ]
    result = {"document": {"elements": [
        {"id": str(i), "type": "paragraph", "text": text, "reading_order": i+1,
         "metadata": {"reading_order_context": context}}
        for i, (text, context) in enumerate(zip(["Second", "Unknown"], contexts))
    ]}}
    path = tmp_path / 'page.blocks.json'
    path.write_text(json.dumps(provider_blocks(result)))
    diff = [_row_to_diff(row) for row in load_blocks(path)]
    assert [b.md for b in diff] == ["Second", "Unknown"]
    assert [b.order_sources for b in diff] == [(contexts[0],), (contexts[1],)]


def test_library_canonical_route_and_copy_preserve_order_context():
    context = {"provider": "mineru", "source": "preproc_blocks.index",
               "page_idx": 3, "native_index": 0}
    block = CanonicalBlock("b", "paragraph", "Text", metadata={"reading_order_context": context})
    diff = block_to_diff(block)
    assert diff.copy().order_sources == (context,)
    assert block_to_diff(CanonicalBlock("legacy", "paragraph", "Text")).order_sources == ()


def test_block_joins_retain_all_contributing_order_sources():
    parts = [DiffBlock(text, "text", (0.1, y, 0.5, y+0.05), text, "paragraph",
                       order_sources=({"provider": "mineru", "page_idx": 0, "native_index": i},))
             for i, (text, y) in enumerate(zip(["Alpha", "Beta", "Gamma"], [0.1, 0.16, 0.22]))]
    expected = tuple(s for p in parts for s in p.order_sources)
    joined = fuse_line_runs(parts, Counter(), "M")
    assert len(joined) == 1
    assert joined[0].order_sources == expected
    owner = DiffBlock("Alpha Beta Gamma", "text", (0, 0, 1, 1), "AlphaBetaGamma", "paragraph")
    grouped = group_split_blocks(parts, [owner], Counter(), "M")
    assert len(grouped) == 1
    assert grouped[0].order_sources == expected


def test_decor_split_keeps_provider_evidence_for_both_fragments():
    source = {"provider": "mineru", "page_idx": 0, "native_index": 2}
    block = DiffBlock("Footer text 12", "text", None, "Footer text 12", "page_footer",
                      order_sources=(source,))
    body, decor = split_decor([block], Counter(), "M")
    assert body == []
    assert len(decor) == 2
    assert all(b.order_sources == (source,) for b in decor)
