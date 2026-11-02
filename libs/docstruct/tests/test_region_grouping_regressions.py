from typing import get_type_hints

import pytest

from docstruct.regions.grouping import (
    _add_unknown_gaps, _extract_callout_title, _fill_gaps_with_unknown,
)
from docstruct.types import Region


def test_known_title_can_span_more_than_two_lines():
    region = Region((0, 0, 100, 100), 'text', 'Important\nOne\nTwo', None, 1, 1,
                    {'line_count': 3})
    assert _extract_callout_title(region, frozenset({'important'})) == 'Important'
    assert _extract_callout_title(region) == ''


def test_gap_helper_annotations_do_not_require_pdf_runtime():
    assert get_type_hints(_fill_gaps_with_unknown)


@pytest.mark.parametrize('covered', [[(0, 0, 200, 200)], [(50, 50, 150, 150)],
                                    [(-10, -10, 100, 210), (100, 0, 210, 100)]])
def test_unknown_gaps_never_overlap_known_content(covered):
    regions = []
    _add_unknown_gaps(covered, 200, 200, regions, 1)
    if covered == [(0, 0, 200, 200)]:
        assert regions == []
    else:
        assert regions
    for region in regions:
        x0, y0, x1, y1 = region.bbox
        assert 0 <= x0 < x1 <= 200 and 0 <= y0 < y1 <= 200
        assert all(not (c[0] < x1 and c[2] > x0 and c[1] < y1 and c[3] > y0)
                   for c in covered)


@pytest.mark.parametrize("extra_candidate", [False, True])
def test_two_block_known_callout_is_merged_without_duplicate_sources(extra_candidate):
    from docstruct.regions.grouping import _merge_callout_groups

    def text_region(box, text):
        return Region(box, "text", text, None, 1, 1)

    regions = [text_region((0, 0, 200, 20), "Main text"),
               text_region((30, 40, 170, 60), "Important"),
               text_region((30, 65, 170, 85), "Callout body")]
    if extra_candidate:
        regions.append(text_region((30, 150, 170, 170), "Separate content"))
    merged = _merge_callout_groups(regions, 200, frozenset({"important"}))
    assert len(merged) == len(regions) - 1
    assert sum(region.text.count("Callout body") for region in merged) == 1
    assert any(region.metadata.get("subtype") == "callout" for region in merged)
