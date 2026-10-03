"""XY-cut reading order: pure ordering, the page reorder helper and the merge_blocks option."""
from collections import Counter

import pytest

from docstruct.fusion.differ import merge_blocks
from docstruct.fusion.types import DiffBlock
from docstruct.fusion.xycut import column_balance, count_columns, reorder, xycut_order
from docstruct.policy import FusionPolicy

# Two columns on a unit page: left column x in [0.08, 0.46], right column x in [0.54, 0.92].
L1, L2 = (0.08, 0.10, 0.46, 0.30), (0.08, 0.32, 0.46, 0.60)
R1, R2 = (0.54, 0.10, 0.92, 0.30), (0.54, 0.32, 0.92, 0.60)
TITLE = (0.08, 0.02, 0.92, 0.07)
FOOTNOTE = (0.08, 0.70, 0.92, 0.78)


def mk(text, box=None, kind="text", md=None, **kw):
    return DiffBlock(md=md or text, kind=kind, box=box, text=text, type=kw.pop("type", kind), **kw)


class TestXYCutOrder:
    def test_two_columns_read_left_column_first(self):
        # incoming order interleaves the columns row by row
        boxes = [L1, R1, L2, R2]
        assert xycut_order(boxes) == [0, 2, 1, 3]

    def test_full_width_blocks_split_sections(self):
        boxes = [R1, FOOTNOTE, L2, TITLE, L1, R2]
        assert [boxes[i] for i in xycut_order(boxes)] == [TITLE, L1, L2, R1, R2, FOOTNOTE]

    def test_three_columns(self):
        cols = [(0.05, 0.1, 0.30, 0.5), (0.37, 0.1, 0.63, 0.5), (0.70, 0.1, 0.95, 0.5)]
        tops = [(x0, 0.1, x1, 0.3) for x0, _, x1, _ in cols]
        bottoms = [(x0, 0.32, x1, 0.5) for x0, _, x1, _ in cols]
        boxes = [tops[2], bottoms[0], tops[0], bottoms[2], tops[1], bottoms[1]]
        ordered = [boxes[i] for i in xycut_order(boxes)]
        assert ordered == [tops[0], bottoms[0], tops[1], bottoms[1], tops[2], bottoms[2]]

    def test_single_column_is_top_down(self):
        boxes = [(0.1, 0.5, 0.9, 0.6), (0.1, 0.1, 0.9, 0.2), (0.1, 0.3, 0.9, 0.4)]
        assert xycut_order(boxes) == [1, 2, 0]

    def test_narrow_marginal_column_is_not_a_column(self):
        # line numbers in the margin (1% of the page wide) must not split the text column
        text = [(0.10, 0.1 + 0.1 * k, 0.90, 0.18 + 0.1 * k) for k in range(4)]
        margin = [(0.02, 0.1 + 0.1 * k, 0.03, 0.12 + 0.1 * k) for k in range(4)]
        assert count_columns(text + margin) == 1

    def test_inverted_axes_are_normalised(self):
        assert xycut_order([(0.46, 0.60, 0.08, 0.32), (0.08, 0.10, 0.46, 0.30)]) == [1, 0]

    def test_count_columns(self):
        assert count_columns([L1, L2, R1, R2]) == 2
        assert count_columns([L1, L2]) == 1
        assert count_columns([]) == 1


class TestReorder:
    def test_multicol_reorders_interleaved_columns(self):
        stats = Counter()
        out = reorder([(L1, "a"), (R1, "c"), (L2, "b"), (R2, "d")], stats=stats)
        assert out == ["a", "b", "c", "d"]
        assert stats["xycut-applied"] == 1
        assert stats["xycut-moved"] == 2

    def test_multicol_keeps_single_column_pages(self):
        stats = Counter()
        items = [((0.1, 0.5, 0.9, 0.6), "late"), ((0.1, 0.1, 0.9, 0.2), "early")]
        assert reorder(items, stats=stats) == ["late", "early"]
        assert stats["xycut-skipped:single-column"] == 1

    def test_always_reorders_single_column_pages(self):
        items = [((0.1, 0.5, 0.9, 0.6), "late"), ((0.1, 0.1, 0.9, 0.2), "early")]
        assert reorder(items, mode="always") == ["early", "late"]

    def test_unboxed_items_follow_their_predecessor(self):
        items = [(None, "lead"), (R1, "c"), (None, "after-c"), (L1, "a"), (L2, "b"), (R2, "d")]
        assert reorder(items) == ["lead", "a", "b", "c", "after-c", "d"]

    def test_nothing_added_or_dropped(self):
        items = [(R2, "d"), (None, "x"), (L1, "a"), ((1, 1, 1, 1), "degenerate"), (R1, "c"), (L2, "b")]
        out = reorder(items, mode="always")
        assert sorted(out) == sorted(p for _, p in items)

    def test_few_boxes_is_a_no_op(self):
        stats = Counter()
        assert reorder([(None, "a"), (L1, "b")], stats=stats) == ["a", "b"]
        assert stats["xycut-skipped:few-boxes"] == 1

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            reorder([(L1, "a"), (R1, "b")], mode="sideways")


class TestColumnBalance:
    # main text column (x 0.05-0.70) next to a narrow sidebar (x 0.76-0.95)
    MAIN1, MAIN2 = (0.05, 0.10, 0.70, 0.40), (0.05, 0.42, 0.70, 0.80)
    SIDE1, SIDE2 = (0.76, 0.10, 0.95, 0.30), (0.76, 0.32, 0.95, 0.50)

    def test_equal_columns_are_balanced(self):
        assert column_balance([L1, L2, R1, R2]) == pytest.approx(1.0)

    def test_sidebar_is_unbalanced(self):
        assert column_balance([self.MAIN1, self.MAIN2, self.SIDE1, self.SIDE2]) < 0.35

    def test_single_column_has_zero_balance(self):
        assert column_balance([L1, L2]) == 0.0

    def test_min_balance_skips_sidebar_pages(self):
        stats = Counter()
        items = [(self.SIDE1, "s1"), (self.MAIN1, "m1"), (self.SIDE2, "s2"), (self.MAIN2, "m2")]
        assert reorder(items, min_balance=0.7, stats=stats) == ["s1", "m1", "s2", "m2"]
        assert stats["xycut-skipped:unbalanced-columns"] == 1
        assert reorder(items) == ["m1", "m2", "s1", "s2"]  # without the balance gate it reorders

    def test_min_balance_keeps_real_columns(self):
        assert reorder([(L1, "a"), (R1, "c"), (L2, "b"), (R2, "d")], min_balance=0.7) == ["a", "b", "c", "d"]


class TestMergeBlocksOption:
    """The MinerU skeleton interleaves two columns; the option restores column order."""

    def _page(self):
        texts = {
            "a": ("Left column first paragraph about the harvest season", L1),
            "b": ("Left column second paragraph continues the story", L2),
            "c": ("Right column first paragraph starts a new topic", R1),
            "d": ("Right column second paragraph closes the page", R2),
        }
        skeleton = ["a", "c", "b", "d"]  # row-wise interleaving (wrong for two columns)
        M = [mk(texts[k][0], texts[k][1]) for k in skeleton]
        D = [mk(texts[k][0], texts[k][1]) for k in "abcd"]
        return D, M

    def test_default_keeps_mineru_skeleton(self):
        D, M = self._page()
        out, _ = merge_blocks(D, M, FusionPolicy(decor_tail=False))
        assert [o.split()[0] + o.split()[1] for o in out] == ["Leftcolumn", "Rightcolumn", "Leftcolumn", "Rightcolumn"]

    def test_multicol_restores_column_order(self):
        D, M = self._page()
        out, stats = merge_blocks(D, M, FusionPolicy(decor_tail=False, order_xycut="multicol"))
        assert [o.split()[0] for o in out] == ["Left", "Left", "Right", "Right"]
        assert stats["xycut-applied"] == 1

    def test_decor_tail_stays_at_the_end(self):
        D, M = self._page()
        # providers never return byte-identical boxes for the same page number
        M.append(mk("42", (0.48, 0.95, 0.52, 0.97)))
        D.append(mk("42", (0.481, 0.951, 0.519, 0.969)))
        out, _ = merge_blocks(D, M, FusionPolicy(order_xycut="multicol"))
        assert out[-1] == "42"
        assert [o.split()[0] for o in out[:-1]] == ["Left", "Left", "Right", "Right"]


class TestPolicy:
    def test_default_is_off(self):
        assert FusionPolicy().order_xycut == "off"
        assert FusionPolicy.drbench_v13().order_xycut == "off"

    def test_invalid_values_raise(self):
        with pytest.raises(ValueError):
            FusionPolicy(order_xycut="diagonal")
        with pytest.raises(ValueError):
            FusionPolicy(xycut_min_columns=1)
        with pytest.raises(ValueError):
            FusionPolicy(xycut_min_balance=1.5)

    def test_round_trip(self):
        p = FusionPolicy(order_xycut="multicol", xycut_min_columns=3)
        assert FusionPolicy.from_dict(p.to_dict()) == p
