"""All source records reach fusion without changing its active geometry."""
import json
from collections import Counter
from copy import deepcopy

from backend.pipeline.fusion import _canonical_to_diff, _group_by_page
from docstruct.fusion.convert import block_to_diff
from docstruct.fusion.noise import fuse_line_runs, group_split_blocks, split_decor
from docstruct.fusion.types import DiffBlock
from docstruct.types import CanonicalBlock
from scripts.drbench.experiments.differ.lib_fuse import _row_to_diff
from scripts.drbench.experiments.differ.tree_differ_v2 import load_blocks
from scripts.drbench.run_pipeline import provider_blocks


def records():
    return [
        {"page_number": 1, "bbox": {"left": 10, "top": 20, "right": 110,
         "bottom": 60, "coord_origin": "TOPLEFT"}, "char_start": 0, "char_end": 5},
        {"page_number": 2, "bbox": {"left": 0, "top": 90, "right": 300,
         "bottom": 40, "coord_origin": "BOTTOMLEFT"}, "char_start": 5, "char_end": 9},
        {"page_number": 3, "bbox": None, "char_start": None, "char_end": None},
    ]


def test_all_records_reach_cli_diff_without_union_or_page_duplication(tmp_path):
    provenance = records()
    payload = {"document": {"pages": [{"page_number": 1, "width": 200, "height": 100}],
        "elements": [{"id": "e1", "type": "paragraph", "text": "Text", "reading_order": 1,
                      "page_number": 1, "provenance": provenance}]}}
    original = deepcopy(payload)
    blocks = provider_blocks(payload)
    assert len(blocks) == 1
    assert blocks[0]["bbox"] == [10, 20, 110, 60]
    assert blocks[0]["provenance"] == provenance
    path = tmp_path/'page.blocks.json'
    path.write_text(json.dumps(blocks))
    diff = [_row_to_diff(b) for b in load_blocks(path)]
    assert len(diff) == 1
    assert diff[0].box == (0.05, 0.2, 0.55, 0.6)
    assert diff[0].provenance == tuple(provenance)
    assert diff[0].copy().provenance == tuple(provenance)
    blocks[0]["provenance"][1]["bbox"]["left"] = 999
    assert payload == original


def test_known_secondary_box_does_not_replace_missing_active_box(tmp_path):
    provenance = records()
    provenance[0]["bbox"] = None
    blocks = provider_blocks({"document": {"elements": [{"type": "paragraph", "text": "Text",
        "reading_order": 1, "provenance": provenance}]}})
    path = tmp_path/'page.blocks.json'
    path.write_text(json.dumps(blocks))
    diff = _row_to_diff(load_blocks(path)[0])
    assert diff.box is None
    assert diff.provenance == tuple(provenance)


def test_backend_and_library_routes_preserve_records_and_existing_active_box():
    provenance = records()
    element = {"type": "paragraph", "text": "Text", "reading_order": 1, "page": 0,
               "bbox": [10, 20, 110, 60], "page_size": [200, 100], "provenance": provenance}
    groups = _group_by_page({"document": {"elements": [element]}})
    assert list(groups) == [0]
    assert len(groups[0]) == 1
    diff = _canonical_to_diff(groups[0][0])
    assert diff.box == (0.05, 0.2, 0.55, 0.6)
    assert diff.provenance == tuple(provenance)
    direct = block_to_diff(CanonicalBlock("b", "paragraph", "Text", metadata={"provenance": provenance}))
    assert direct.provenance == tuple(provenance)
    direct.provenance[0]["bbox"]["left"] = 999
    assert provenance[0]["bbox"]["left"] == 10
    legacy = block_to_diff(CanonicalBlock("old", "paragraph", "Text"))
    assert legacy.provenance == ()


def test_joins_and_decor_splits_retain_provenance_without_deduplication():
    source = records()[0]
    parts = [DiffBlock(text, "text", (0.1, y, 0.5, y+0.05), text, "paragraph",
                       provenance=(deepcopy(source),))
             for text, y in zip(["Alpha", "Beta", "Gamma"], [0.1, 0.16, 0.22])]
    expected = (source, source, source)
    joined = fuse_line_runs(parts, Counter(), "M")
    assert len(joined) == 1
    assert joined[0].provenance == expected
    owner = DiffBlock("AlphaBetaGamma", "text", (0, 0, 1, 1), "AlphaBetaGamma", "paragraph")
    assert group_split_blocks(parts, [owner], Counter(), "M")[0].provenance == expected
    footer = DiffBlock("Footer text 12", "text", None, "Footer text 12", "page_footer",
                       provenance=(source,))
    body, decor = split_decor([footer], Counter(), "M")
    assert not body and len(decor) == 2
    assert all(b.provenance == (source,) for b in decor)
