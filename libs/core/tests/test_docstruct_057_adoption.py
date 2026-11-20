"""Characterization and parity tests for core adoption of docstruct 0.5.7 primitives (#612)."""
from __future__ import annotations

import struct

import pytest
from docstruct.fusion.noise import is_legitimate_text as docstruct_is_legitimate_text
from docstruct.fusion.skeleton import (
    DEFAULT_MIN_SKELETON_MATCH as docstruct_min_skeleton_match,
    skeleton_reading_order as docstruct_skeleton_reading_order,
)
from docstruct.geometry.boxes import (
    box_contains_center,
    box_distance,
    boxes_side_by_side,
    expand_box,
    spans_horizontally,
)

from acessilia_core.agents.output_schemas import DataCell, DataOutput, DataRow
from acessilia_core.manifest import slides
from acessilia_core.manifest.builder import _derive_processing_needs
from acessilia_core.manifest.models import ManifestElement
from acessilia_core.pipeline.elements import (
    _table_ast_from_metadata,
    _table_element_has_structured_content,
)
from acessilia_core.pipeline.handlers import order as order_handler
from acessilia_core.pipeline.handlers.rescue import is_legitimate_text
from acessilia_core.pipeline.handlers.text import _handle_deterministic_heading_repair_method
from acessilia_core.toolbox import vision_payload
from core_config_support import toolbox_config
from pddl_support import build_manifest, build_obligation


def test_rescue_is_legitimate_text_is_docstruct_function() -> None:
    assert is_legitimate_text is docstruct_is_legitimate_text


def test_table_ast_from_metadata_delegates_strict_normalization_and_drops_bool_spans() -> None:
    normalized = _table_ast_from_metadata(
        {
            "table_ast": {
                "caption": "  Results  ",
                "header": [{"cells": [{"text": "A", "header": True, "scope": "col"}]}],
                "body": [
                    {
                        "cells": [
                            {"text": 10, "rowspan": True, "colspan": 2},
                            {"header": True},  # missing text -> dropped
                        ]
                    }
                ],
                "metadata": {"source": "docling"},
            }
        }
    )
    assert normalized == {
        "caption": "Results",
        "header": [{"cells": [{"text": "A", "header": True, "scope": "col"}]}],
        "body": [{"cells": [{"text": "10", "colspan": 2}]}],
        "metadata": {"source": "docling"},
    }


def test_table_element_has_structured_content_passes_localized_placeholder() -> None:
    placeholder = ManifestElement(
        id="tbl-1",
        type="table",
        raw_label="table",
        reading_order=1,
        hierarchy_level=0,
        metadata={"table_ast": {"body": [{"cells": [{"text": "Tabela detectada"}]}]}},
    )
    real = ManifestElement(
        id="tbl-2",
        type="table",
        raw_label="table",
        reading_order=2,
        hierarchy_level=0,
        metadata={"table_ast": {"body": [{"cells": [{"text": "Only real cell"}]}]}},
    )
    assert _table_element_has_structured_content(placeholder) is False
    assert _table_element_has_structured_content(real) is True


def test_data_output_table_ast_delegates_to_docstruct_structured_builder() -> None:
    output = DataOutput(
        kind="table",
        language="en",
        confidence=0.95,
        caption="Summary",
        rows=[
            DataRow(
                cells=[
                    DataCell(text="Metric", header=True, scope="col"),
                    DataCell(text="Score", header=True, scope="col"),
                ]
            ),
            DataRow(
                cells=[
                    DataCell(text="F1", scope="row"),
                    DataCell(text="0.98"),
                ]
            ),
        ],
        notes=["Note A"],
        warnings=["minor OCR noise"],
    )
    assert output.table_ast() == {
        "header": [
            {
                "cells": [
                    {"text": "Metric", "header": True, "scope": "col"},
                    {"text": "Score", "header": True, "scope": "col"},
                ]
            }
        ],
        "body": [
            {
                "cells": [
                    {"text": "F1", "header": True, "scope": "row"},
                    {"text": "0.98"},
                ]
            }
        ],
        "caption": "Summary",
        "footer": [{"cells": [{"text": "Note A", "colspan": 2}]}],
        "metadata": {"warnings": ["minor OCR noise"]},
    }


def test_heading_gap_detection_and_repair_stay_in_sync() -> None:
    elements = [
        ManifestElement(
            id="element-h1",
            type="heading",
            raw_label="heading",
            text="Start",
            hierarchy_level=2,
            reading_order=1,
            page_number=1,
        ),
        ManifestElement(
            id="element-h2",
            type="heading",
            raw_label="heading",
            text="Jump",
            hierarchy_level=5,
            reading_order=2,
            page_number=1,
        ),
        ManifestElement(
            id="element-h3",
            type="title",
            raw_label="title",
            text="Second title",
            hierarchy_level=1,
            reading_order=3,
            page_number=1,
        ),
    ]
    observations, obligations = _derive_processing_needs(elements)
    gap_obs = [obs for obs in observations if obs.kind == "heading-hierarchy-gap"]
    assert [obs.evidence for obs in gap_obs] == [
        {"previous_level": 0, "current_level": 2},
        {"previous_level": 2, "current_level": 5},
        {"previous_level": 5, "current_level": 1},
    ]

    repair_ob = build_obligation(
        "repair-heading-hierarchy",
        ["element-h1", "element-h2", "element-h3"],
        ["deterministic-heading-repair", "human-review"],
    )
    manifest = build_manifest(elements, [repair_ob])
    result = _handle_deterministic_heading_repair_method(manifest, repair_ob.id)
    assert result.success is True
    assert [(el.type, el.hierarchy_level) for el in manifest.elements] == [
        ("heading", 1),
        ("heading", 2),
        ("heading", 2),
    ]
    after_obs, _ = _derive_processing_needs(manifest.elements)
    assert [obs for obs in after_obs if obs.kind == "heading-hierarchy-gap"] == []


@pytest.mark.asyncio
async def test_downscale_image_uses_docstruct_image_dimensions() -> None:
    # A 1x1 PNG cannot get smaller at scale=0.5 (max_side=max(1, 0)=1 >= 1), so
    # downscale_image returns None without touching the Toolbox.
    tiny_png = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1, 1)
        + b"\x08\x02\x00\x00\x00"
    )
    assert await vision_payload.downscale_image(tiny_png, scale=0.5, toolbox=toolbox_config()) is None
    assert await vision_payload.downscale_image(b"not-an-image", scale=0.5, toolbox=toolbox_config()) is None


def test_skeleton_order_wiring_ranking_and_threshold_are_unchanged() -> None:
    assert order_handler.skeleton_reading_order is docstruct_skeleton_reading_order
    assert order_handler._MIN_SKELETON_MATCH == docstruct_min_skeleton_match == 0.5
    # The ranking pins the primitive itself; the second call pins the 0.5
    # threshold (DEFAULT_MIN_SKELETON_MATCH): one match in four is too few.
    assert order_handler.skeleton_reading_order(
        5, {0: 3, 1: 0, 3: 4}, min_match_ratio=order_handler._MIN_SKELETON_MATCH
    ) == [1, 2, 0, 3, 4]
    assert (
        order_handler.skeleton_reading_order(
            4, {0: 0}, min_match_ratio=order_handler._MIN_SKELETON_MATCH
        )
        is None
    )


def test_slide_box_helpers_wiring_and_formulas_are_unchanged() -> None:
    assert slides.box_contains_center is box_contains_center
    assert slides.expand_box is expand_box
    assert slides.spans_horizontally is spans_horizontally
    assert slides.boxes_side_by_side is boxes_side_by_side
    assert slides.box_distance is box_distance

    picture, box = (0.0, 0.0, 1.0, 1.0), (0.4, 0.1, 0.6, 0.3)
    assert slides.box_contains_center(picture, box) is True
    assert slides.expand_box(picture, 0.1) == (-0.1, -0.1, 1.1, 1.1)
    assert slides.spans_horizontally(picture, box) is True
    assert slides.boxes_side_by_side([picture, box]) is True
    assert slides.boxes_side_by_side([picture, (0.0, 2.0, 1.0, 3.0)]) is False
    assert slides.box_distance(picture, box) == 0.0
    assert slides.box_distance(picture, (2.0, 0.0, 3.0, 1.0)) == 1.0
