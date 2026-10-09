"""Unit tests for DR-Bench adjudication improvements across all 5 pillars:
1. Reading Order refinement with gutter partitioning and marginal isolation
2. Omitted block rescue (unmatched_gt:body)
3. Formula LaTeX normalization
4. VLM adjudication expansion (dispute threshold 0.94, pred_shorter)
5. Smart hybrid table fusion with span/complexity inspection
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest

from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.manifest.builder import (
    build_processing_manifest,
    _refine_reading_order,
    _order_body_elements_by_column,
)
from backend.core.manifest.docling_extractor import DoclingExtraction
from backend.core.manifest.models import ManifestElement, Provenance, BoundingBox
from backend.tools.formula_tools import normalize_latex, wrap_latex
from scripts.drbench.experiments.differ.tree_differ_v2 import (
    is_legitimate_text,
    suppress_in_regions,
    merge_v2,
)
from scripts.drbench.experiments.analysis.block_oracle import (
    evaluate_oracle_headroom,
    classify_block,
    compute_edit_dist,
)


def make_element(
    id: str,
    type: str,
    raw_label: str,
    reading_order: int,
    page_number: int | None = 1,
    bbox: tuple[float, float, float, float] | None = None,
    text: str = "",
    parent_id: str | None = None,
) -> ManifestElement:
    prov = []
    if page_number is not None and bbox is not None:
        prov.append(
            Provenance(
                page_number=page_number,
                bbox=BoundingBox(
                    left=bbox[0], top=bbox[1], right=bbox[2], bottom=bbox[3]
                ),
            )
        )
    return ManifestElement(
        id=id,
        type=type,  # type: ignore[arg-type]
        raw_label=raw_label,
        reading_order=reading_order,
        hierarchy_level=0,
        text=text,
        page_number=page_number,
        provenance=prov,
        parent_id=parent_id,
    )


# =========================================================================
# Pillar 1: Reading Order Refinement
# =========================================================================

def test_reading_order_refinement_marginal_isolation():
    """Verify headers are placed at top, body in middle, and footers/page numbers at bottom."""
    root = make_element(
        id="root",
        type="group",
        raw_label="group",
        reading_order=1,
        page_number=None,
    )
    # Page 1 elements in jumbled order
    footer = make_element(
        id="f1",
        type="page_footer",
        raw_label="page_footer",
        reading_order=2,
        page_number=1,
        bbox=(50.0, 750.0, 200.0, 770.0),
        text="Footer Note",
        parent_id="root",
    )
    body1 = make_element(
        id="b1",
        type="paragraph",
        raw_label="paragraph",
        reading_order=3,
        page_number=1,
        bbox=(50.0, 200.0, 250.0, 400.0),
        text="Body text column 1",
        parent_id="root",
    )
    header = make_element(
        id="h1",
        type="page_header",
        raw_label="page_header",
        reading_order=4,
        page_number=1,
        bbox=(50.0, 30.0, 300.0, 50.0),
        text="Header Title",
        parent_id="root",
    )
    pagenum = make_element(
        id="p1",
        type="paragraph",
        raw_label="page_number",
        reading_order=5,
        page_number=1,
        bbox=(250.0, 780.0, 270.0, 795.0),
        text="1",
        parent_id="root",
    )

    refined = _refine_reading_order([root, footer, body1, header, pagenum])

    # Root container stays at index 0 with reading_order 1
    assert refined[0].id == "root"
    assert refined[0].page_number is None
    assert refined[0].reading_order == 1

    # Header is at top of page 1
    assert refined[1].id == "h1"
    assert refined[1].type == "page_header"
    assert refined[1].reading_order == 2

    # Body is next
    assert refined[2].id == "b1"
    assert refined[2].type == "paragraph"
    assert refined[2].reading_order == 3

    # Footers and page numbers at the bottom
    tail_ids = {refined[3].id, refined[4].id}
    assert tail_ids == {"f1", "p1"}


def test_reading_order_refinement_multi_column_gutters():
    """Verify column partitioning orders left column top-to-bottom then right column."""
    # 2 columns layout:
    # Left col: x in [50, 250]
    # Right col: x in [300, 500]
    col1_top = make_element(
        id="c1_top", type="paragraph", raw_label="paragraph", reading_order=1,
        page_number=1, bbox=(50.0, 100.0, 250.0, 200.0), parent_id="root",
    )
    col1_bot = make_element(
        id="c1_bot", type="paragraph", raw_label="paragraph", reading_order=2,
        page_number=1, bbox=(50.0, 250.0, 250.0, 400.0), parent_id="root",
    )
    col2_top = make_element(
        id="c2_top", type="paragraph", raw_label="paragraph", reading_order=3,
        page_number=1, bbox=(300.0, 100.0, 500.0, 200.0), parent_id="root",
    )
    col2_bot = make_element(
        id="c2_bot", type="paragraph", raw_label="paragraph", reading_order=4,
        page_number=1, bbox=(300.0, 250.0, 500.0, 400.0), parent_id="root",
    )

    # If incoming list is sorted purely by Y (horizontal raster scan across columns)
    raster = [col1_top, col2_top, col1_bot, col2_bot]
    ordered = _order_body_elements_by_column(raster)
    ordered_ids = [el.id for el in ordered]

    # Must be ordered left column first (col1_top, col1_bot), then right column (col2_top, col2_bot)
    assert ordered_ids == ["c1_top", "c1_bot", "c2_top", "c2_bot"]


def test_informational_agent_uses_refine_reading_order(tmp_path: Path):
    """Verify InformationalStructuralAgent processes documents with refine_reading_order."""
    class SampleDoc:
        def __init__(self) -> None:
            prov_footer = SimpleNamespace(
                page_no=1,
                bbox=SimpleNamespace(l=50, t=750, r=200, b=770, coord_origin=SimpleNamespace(value="TOPLEFT")),
                charspan=(0, 6),
            )
            prov_header = SimpleNamespace(
                page_no=1,
                bbox=SimpleNamespace(l=50, t=30, r=200, b=50, coord_origin=SimpleNamespace(value="TOPLEFT")),
                charspan=(0, 6),
            )
            self.items = [
                (SimpleNamespace(label=None, name="body", self_ref="#/body", parent=None), 0),
                (
                    SimpleNamespace(
                        label=SimpleNamespace(value="page_footer"),
                        text="Footer note",
                        prov=[prov_footer],
                        self_ref="#/texts/0",
                        parent=SimpleNamespace(cref="#/body"),
                        content_layer=SimpleNamespace(value="body"),
                    ),
                    1,
                ),
                (
                    SimpleNamespace(
                        label=SimpleNamespace(value="page_header"),
                        text="Header title",
                        prov=[prov_header],
                        self_ref="#/texts/1",
                        parent=SimpleNamespace(cref="#/body"),
                        content_layer=SimpleNamespace(value="body"),
                    ),
                    1,
                ),
            ]
            self.pages = {1: SimpleNamespace(size=SimpleNamespace(width=595, height=842))}

        def iterate_items(self, **_: object):
            return iter(self.items)

        def num_pages(self) -> int:
            return 1

    class CustomExtractor:
        def extract(self, _: Path) -> DoclingExtraction:
            t = datetime(2026, 10, 9, tzinfo=timezone.utc)
            return DoclingExtraction(
                document=SampleDoc(),
                started_at=t,
                completed_at=t,
                duration_ms=10,
                version="1.0",
                configuration={"extractor": "docling"},
            )

    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    agent = InformationalStructuralAgent(extractor=CustomExtractor())  # type: ignore[arg-type]
    manifest = agent.process(source)

    # Element 0 is root group, element 1 must be header, element 2 must be footer
    assert manifest.elements[0].page_number is None
    assert manifest.elements[1].raw_label == "page_header"
    assert manifest.elements[2].raw_label == "page_footer"


# =========================================================================
# Pillar 2: Omitted Block Rescue
# =========================================================================

def test_is_legitimate_text():
    """Verify is_legitimate_text distinguishes genuine body text from noise."""
    legit_block = {
        "kind": "text",
        "text": "The quick brown fox jumps over the lazy dog.",
        "md": "The quick brown fox jumps over the lazy dog.",
    }
    assert is_legitimate_text(legit_block) is True

    short_label = {
        "kind": "text",
        "text": "12",
        "md": "12",
    }
    assert is_legitimate_text(short_label) is False

    non_alpha = {
        "kind": "text",
        "text": "!@#$%^&*()",
        "md": "!@#$%^&*()",
    }
    assert is_legitimate_text(non_alpha) is False

    table_block = {
        "kind": "table",
        "text": "Column A Column B",
        "md": "| Column A | Column B |",
    }
    assert is_legitimate_text(table_block) is False


def test_suppress_in_regions_rescue_omitted():
    """Verify legitimate text inside picture bboxes is rescued when rescue_omitted=True."""
    m_pics = [[0.1, 0.1, 0.8, 0.8]]
    legit_block = {
        "kind": "text",
        "box": [0.2, 0.2, 0.6, 0.3],
        "text": "Important caption explaining the diagram in details.",
        "md": "Important caption explaining the diagram in details.",
    }
    garbage_block = {
        "kind": "text",
        "box": [0.4, 0.4, 0.5, 0.5],
        "text": "1a 2b 3c ???",
        "md": "1a 2b 3c ???",
    }
    stats = Counter()

    survivors = suppress_in_regions(
        [legit_block, garbage_block], [], m_pics, stats, rescue_omitted=True, pic_min_blocks=1
    )
    assert any(b["text"] == legit_block["text"] for b in survivors)
    assert stats["rescued-in-picture"] >= 1


# =========================================================================
# Pillar 3: Formula LaTeX Normalization
# =========================================================================

def test_normalize_latex_delimiters():
    """Verify stripping of display and inline delimiters."""
    assert normalize_latex(r"$$ E = mc^2 $$") == r"E = mc^2"
    assert normalize_latex(r"\[ \int_0^1 x dx \]") == r"\int_0^1 x dx"
    assert normalize_latex(r"\( \alpha + \beta \)") == r"\alpha + \beta"
    assert normalize_latex(r"$ x \le y $") == r"x \le y"


def test_normalize_latex_unicode_and_spacing():
    """Verify Unicode minus, spaces, and macro spacing are standardized."""
    expr = "x \u2212 5 = 0"
    assert normalize_latex(expr) == "x - 5 = 0"

    spaced = r"a \, b \; c \quad d"
    norm_res = normalize_latex(spaced)
    assert r"\," not in norm_res
    assert r"\quad" not in norm_res


def test_wrap_latex():
    """Verify wrap_latex correctly applies inline or display syntax."""
    assert wrap_latex("x^2", display=False) == "$x^2$"
    assert wrap_latex("x^2", display=True) == "$$x^2$$"
    assert wrap_latex("$x^2$", display=False) == "$x^2$"


# =========================================================================
# Pillar 4: VLM Adjudication Expansion
# =========================================================================

def test_vlm_queue_on_similarity_and_pred_shorter():
    """Verify merge_v2 flags disputes below threshold (0.94) and on pred_shorter divergences."""
    docling_blocks = [
        {
            "kind": "text",
            "type": "paragraph",
            "box": [0.1, 0.1, 0.5, 0.2],
            "text": "This is a detailed paragraph with extensive explanations about the experiment.",
            "md": "This is a detailed paragraph with extensive explanations about the experiment.",
        }
    ]
    mineru_blocks = [
        {
            "kind": "text",
            "type": "paragraph",
            "box": [0.1, 0.1, 0.5, 0.2],
            "text": "This is a detailed paragraph truncated.",
            "md": "This is a detailed paragraph truncated.",
        }
    ]

    vlm_queue: list[dict] = []
    blocks, stats = merge_v2(
        docling_blocks,
        mineru_blocks,
        lam=0.5,
        tau=0.6,
        min_len=10,
        table_pref="mineru",
        formula_pref="mineru",
        queue_sim=0.94,
        queue_pred_shorter=True,
        vlm_queue=vlm_queue,
        item_id="test_doc",
    )

    assert stats["vlm-disputed"] >= 1
    assert len(vlm_queue) == 1
    assert vlm_queue[0]["item"] == "test_doc"
    assert vlm_queue[0]["is_pred_shorter"] is True


def test_vlm_decisions_resolution():
    """Verify vlm_decisions overrides default text pick."""
    d_block = {
        "kind": "text",
        "type": "paragraph",
        "box": [0.1, 0.1, 0.5, 0.2],
        "text": "Docling text version with high accuracy.",
        "md": "Docling text version with high accuracy.",
    }
    m_block = {
        "kind": "text",
        "type": "paragraph",
        "box": [0.1, 0.1, 0.5, 0.2],
        "text": "MinerU text version with some ocr error.",
        "md": "MinerU text version with some ocr error.",
    }

    decisions = {"doc_item:0": "docling"}
    blocks, stats = merge_v2(
        [d_block],
        [m_block],
        lam=0.5,
        tau=0.6,
        min_len=10,
        table_pref="mineru",
        formula_pref="mineru",
        text_pick="mineru",
        vlm_decisions=decisions,
        item_id="doc_item",
    )

    assert blocks[0] == d_block["md"]
    assert stats["pair-text->vlm(docling)"] == 1


# =========================================================================
# Pillar 5: Smart Hybrid Table Fusion
# =========================================================================

def test_smart_hybrid_table_fusion():
    """Verify Docling is preferred when table has spans/complexity, MinerU otherwise."""
    d_table_complex = {
        "kind": "table",
        "type": "table",
        "box": [0.1, 0.3, 0.9, 0.6],
        "text": "Col1 Col2",
        "md": '<table><tr><td rowspan="2">Multi</td><td>A</td></tr></table>',
        "metadata": {"table_has_spans": True, "table_is_complex": True},
    }
    m_table_complex = {
        "kind": "table",
        "type": "table",
        "box": [0.1, 0.3, 0.9, 0.6],
        "text": "Col1 Col2",
        "md": "| Col1 | Col2 |\n|---|---|\n| Multi | A |",
    }

    blocks, stats = merge_v2(
        [d_table_complex],
        [m_table_complex],
        lam=0.5,
        tau=0.6,
        min_len=5,
        table_pref="mineru",
        formula_pref="mineru",
        table_smart_fusion=True,
    )
    assert blocks[0] == d_table_complex["md"]
    assert stats["pair-table->docling(spans)"] == 1

    d_table_simple = {
        "kind": "table",
        "type": "table",
        "box": [0.1, 0.3, 0.9, 0.6],
        "text": "Col1 Col2",
        "md": "| Col1 | Col2 |\n|---|---|\n| A | B |",
        "metadata": {"table_has_spans": False, "table_is_complex": False},
    }
    m_table_simple = {
        "kind": "table",
        "type": "table",
        "box": [0.1, 0.3, 0.9, 0.6],
        "text": "Col1 Col2",
        "md": "| Col1 | Col2 |\n|---|---|\n| A | B |",
    }
    blocks_simple, stats_simple = merge_v2(
        [d_table_simple],
        [m_table_simple],
        lam=0.5,
        tau=0.6,
        min_len=5,
        table_pref="mineru",
        formula_pref="mineru",
        table_smart_fusion=True,
    )
    assert blocks_simple[0] == m_table_simple["md"]
    assert stats_simple["pair-table->mineru"] == 1


# =========================================================================
# Block Oracle Analysis Evaluation
# =========================================================================

def test_evaluate_oracle_headroom():
    """Verify evaluate_oracle_headroom computes positive headroom gain from best candidates."""
    base_records = [
        {
            "img_id": "page_001.jpg",
            "gt": "Hello World",
            "norm_gt": "HelloWorld",
            "norm_pred": "HxlloWorld",
            "Edit_num": 1,
            "upper_len": 10,
            "gt_position": ["1"],
            "pred_position": "1",
        }
    ]
    doc_records = [
        {
            "img_id": "page_001.jpg",
            "gt": "Hello World",
            "norm_gt": "HelloWorld",
            "norm_pred": "HelloWorld",
            "gt_position": ["1"],
            "pred_position": "1",
        }
    ]
    min_records = [
        {
            "img_id": "page_001.jpg",
            "gt": "Hello World",
            "norm_gt": "HelloWorld",
            "norm_pred": "HxlloWorld",
            "gt_position": ["1"],
            "pred_position": "1",
        }
    ]

    res = evaluate_oracle_headroom(base_records, doc_records, min_records)

    assert res["n_pages"] == 1
    assert res["baseline_text_score"] == 90.0
    assert res["oracle_text_score"] == 100.0
    assert res["headroom_pts"] == 10.0
    assert res["provider_wins"]["docling"] == 1
