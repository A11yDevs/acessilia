"""Tests for multi-column reading order refinement in docstruct.geometry.reading_order."""
from __future__ import annotations

from docstruct.geometry.reading_order import refine_reading_order
from docstruct.types import CanonicalBlock


class TestReadingOrderMarginals:
    def test_marginal_isolation(self):
        blocks = [
            CanonicalBlock(id="footer", type="page_footer", text="Page 1 Footer", bbox=(50.0, 750.0, 200.0, 770.0), page_index=1),
            CanonicalBlock(id="body1", type="paragraph", text="Body text paragraph", bbox=(50.0, 200.0, 250.0, 400.0), page_index=1),
            CanonicalBlock(id="header", type="page_header", text="Page 1 Header", bbox=(50.0, 30.0, 250.0, 50.0), page_index=1),
            CanonicalBlock(id="pagenum", type="page_number", text="1", bbox=(250.0, 780.0, 270.0, 795.0), page_index=1),
        ]

        refined = refine_reading_order(blocks)
        ids = [b.id for b in refined]

        # Header must be at top
        assert ids[0] == "header"
        # Body in the middle
        assert ids[1] == "body1"
        # Footers at bottom
        assert set(ids[2:]) == {"footer", "pagenum"}

    def test_document_level_container_preserved_at_start(self):
        root = CanonicalBlock(id="root", type="group", text="", bbox=None, page_index=None)
        p1 = CanonicalBlock(id="p1", type="paragraph", text="Content", bbox=(50.0, 100.0, 200.0, 200.0), page_index=1)

        refined = refine_reading_order([root, p1])
        assert refined[0].id == "root"
        assert refined[1].id == "p1"


class TestMultiColumnReadingOrder:
    def test_two_columns_read_left_column_first(self):
        # 2 columns layout:
        # Left col: x in [50, 250]
        # Right col: x in [300, 500]
        c1_top = CanonicalBlock(id="c1_top", type="paragraph", text="Col 1 Top", bbox=(50.0, 100.0, 250.0, 200.0), page_index=1)
        c1_bot = CanonicalBlock(id="c1_bot", type="paragraph", text="Col 1 Bot", bbox=(50.0, 250.0, 250.0, 400.0), page_index=1)
        c2_top = CanonicalBlock(id="c2_top", type="paragraph", text="Col 2 Top", bbox=(300.0, 100.0, 500.0, 200.0), page_index=1)
        c2_bot = CanonicalBlock(id="c2_bot", type="paragraph", text="Col 2 Bot", bbox=(300.0, 250.0, 500.0, 400.0), page_index=1)

        # Interleaved (raster scan across columns)
        interleaved = [c1_top, c2_top, c1_bot, c2_bot]
        refined = refine_reading_order(interleaved)
        ids = [b.id for b in refined]

        # Must read column 1 top-to-bottom, then column 2 top-to-bottom
        assert ids == ["c1_top", "c1_bot", "c2_top", "c2_bot"]

    def test_three_columns_read_sequentially(self):
        # 3 columns layout:
        # Col 1: [50, 150]
        # Col 2: [200, 300]
        # Col 3: [350, 450]
        c1_1 = CanonicalBlock(id="c1_1", type="paragraph", text="1A", bbox=(50.0, 100.0, 150.0, 200.0), page_index=1)
        c1_2 = CanonicalBlock(id="c1_2", type="paragraph", text="1B", bbox=(50.0, 250.0, 150.0, 350.0), page_index=1)
        c2_1 = CanonicalBlock(id="c2_1", type="paragraph", text="2A", bbox=(200.0, 100.0, 300.0, 200.0), page_index=1)
        c2_2 = CanonicalBlock(id="c2_2", type="paragraph", text="2B", bbox=(200.0, 250.0, 300.0, 350.0), page_index=1)
        c3_1 = CanonicalBlock(id="c3_1", type="paragraph", text="3A", bbox=(350.0, 100.0, 450.0, 200.0), page_index=1)
        c3_2 = CanonicalBlock(id="c3_2", type="paragraph", text="3B", bbox=(350.0, 250.0, 450.0, 350.0), page_index=1)

        interleaved = [c1_1, c2_1, c3_1, c1_2, c2_2, c3_2]
        refined = refine_reading_order(interleaved)
        ids = [b.id for b in refined]

        assert ids == ["c1_1", "c1_2", "c2_1", "c2_2", "c3_1", "c3_2"]

    def test_full_width_banner_splits_sections(self):
        title = CanonicalBlock(id="title", type="heading", text="Full Title", bbox=(50.0, 50.0, 500.0, 80.0), page_index=1)
        c1_top = CanonicalBlock(id="c1_top", type="paragraph", text="Col 1 Top", bbox=(50.0, 100.0, 250.0, 200.0), page_index=1)
        c1_bot = CanonicalBlock(id="c1_bot", type="paragraph", text="Col 1 Bot", bbox=(50.0, 250.0, 250.0, 350.0), page_index=1)
        c2_top = CanonicalBlock(id="c2_top", type="paragraph", text="Col 2 Top", bbox=(300.0, 100.0, 500.0, 200.0), page_index=1)
        c2_bot = CanonicalBlock(id="c2_bot", type="paragraph", text="Col 2 Bot", bbox=(300.0, 250.0, 500.0, 350.0), page_index=1)

        interleaved = [title, c2_top, c1_top, c2_bot, c1_bot]
        refined = refine_reading_order(interleaved)
        ids = [b.id for b in refined]

        assert ids == ["title", "c1_top", "c1_bot", "c2_top", "c2_bot"]

    def test_mid_page_banner_splits_column_sections(self):
        s1_c1 = CanonicalBlock(id="s1_c1", type="paragraph", text="Sec 1 Col 1", bbox=(50.0, 100.0, 250.0, 200.0), page_index=1)
        s1_c2 = CanonicalBlock(id="s1_c2", type="paragraph", text="Sec 1 Col 2", bbox=(300.0, 100.0, 500.0, 200.0), page_index=1)
        mid_banner = CanonicalBlock(id="mid_banner", type="heading", text="Mid Banner", bbox=(50.0, 220.0, 500.0, 250.0), page_index=1)
        s2_c1 = CanonicalBlock(id="s2_c1", type="paragraph", text="Sec 2 Col 1", bbox=(50.0, 270.0, 250.0, 370.0), page_index=1)
        s2_c2 = CanonicalBlock(id="s2_c2", type="paragraph", text="Sec 2 Col 2", bbox=(300.0, 270.0, 500.0, 370.0), page_index=1)

        interleaved = [s2_c2, s1_c2, mid_banner, s2_c1, s1_c1]
        refined = refine_reading_order(interleaved)
        ids = [b.id for b in refined]

        assert ids == ["s1_c1", "s1_c2", "mid_banner", "s2_c1", "s2_c2"]

    def test_single_column_page_stays_top_down(self):
        b1 = CanonicalBlock(id="b1", type="paragraph", text="P1", bbox=(50.0, 100.0, 450.0, 150.0), page_index=1)
        b2 = CanonicalBlock(id="b2", type="paragraph", text="P2", bbox=(50.0, 160.0, 450.0, 220.0), page_index=1)
        b3 = CanonicalBlock(id="b3", type="paragraph", text="P3", bbox=(50.0, 230.0, 450.0, 300.0), page_index=1)

        refined = refine_reading_order([b3, b1, b2])
        assert [b.id for b in refined] == ["b1", "b2", "b3"]

    def test_provenance_guards_without_bbox(self):
        # Empty list, non-subscriptable object, None provenance
        class DummyBlock:
            def __init__(self, prov):
                self.provenance = prov
                self.type = "paragraph"
                self.page_index = 1

        b_empty = DummyBlock([])
        b_none = DummyBlock(None)
        b_str = DummyBlock("invalid_non_sequence")

        # Must not raise IndexError or TypeError
        refined = refine_reading_order([b_empty, b_none, b_str])
        assert len(refined) == 3
