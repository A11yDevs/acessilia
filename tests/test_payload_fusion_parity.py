"""Contract parity between docstruct.fusion.payload and acessilia_core.pipeline.fusion (#612).

PR 4 introduced pure multi-provider payload fusion and page routing in
``docstruct.fusion.payload`` while ``acessilia_core.pipeline.fusion`` still held
its own copy; PR 6 delegated the core wrappers to ``docstruct.fusion.payload``.
This suite stays as a regression guard ensuring the core logging/adapter layer
introduces zero drift relative to ``docstruct.fusion.payload`` across policy
presets, edge-case payloads, and the pure-Python fallback without ``rapidfuzz``.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest
from acessilia_core.pipeline import fusion as core_fusion
from docstruct.fusion import payload as docstruct_fusion
from docstruct.policy import FusionPolicy

_WORDS = (
    "accessibility",
    "document",
    "structure",
    "heading",
    "table",
    "caption",
    "figure",
    "formula",
    "reading",
    "order",
    "page",
    "column",
    "section",
    "paragraph",
    "footnote",
    "summary",
    "alpha",
    "beta",
    "gamma",
)

_ELEMENT_TYPES = (
    "paragraph",
    "heading",
    "title",
    "table",
    "picture",
    "formula",
    "list_item",
)


def _random_text(rng: random.Random, *, min_words: int = 0, max_words: int = 12) -> str:
    count = rng.randint(min_words, max_words)
    if count == 0:
        return ""
    return " ".join(rng.choices(_WORDS, k=count))


def _random_bbox(rng: random.Random) -> Any:
    mode = rng.random()
    if mode < 0.25:
        return None
    left = round(rng.uniform(0.0, 400.0), 1)
    top = round(rng.uniform(0.0, 600.0), 1)
    right = round(left + rng.uniform(10.0, 200.0), 1)
    bottom = round(top + rng.uniform(10.0, 200.0), 1)
    if mode < 0.55:
        return [left, top, right, bottom]
    if mode < 0.85:
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "coord_origin": "TOPLEFT",
        }
    return [left, "invalid", right, bottom]


def _random_payload(
    rng: random.Random,
    *,
    prefix: str,
    page_count: int,
    zero_based: bool = False,
    wrap_document: bool = True,
    allow_missing_id: bool = False,
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    element_ids: list[str] = []
    width = rng.choice([600.0, 800.0, 1200.0])
    height = rng.choice([800.0, 1000.0, 1600.0])

    reading_order = 1
    for page_num in range(1, page_count + 1):
        count = rng.randint(0, 5)
        for _ in range(count):
            etype = rng.choice(_ELEMENT_TYPES)
            text = _random_text(rng, min_words=0 if etype in {"picture", "table", "formula"} else 1)
            el_id = (
                None
                if allow_missing_id and rng.random() < 0.15
                else f"{prefix}-{reading_order}"
            )
            element: dict[str, Any] = {
                "type": etype,
                "text": text,
                "reading_order": reading_order,
                "page_size": [width, height],
                "coord_origin": "TOPLEFT",
            }
            if el_id is not None:
                element["id"] = el_id
                element_ids.append(el_id)
            if element_ids and rng.random() < 0.2:
                element["parent_id"] = rng.choice(element_ids)
            if zero_based:
                element["page"] = page_num - 1
            else:
                element["page_number"] = page_num
            bbox = _random_bbox(rng)
            if bbox is not None:
                if rng.random() < 0.5:
                    element["bbox"] = bbox
                else:
                    element["provenance"] = [{"page_number": page_num, "bbox": bbox}]
            if etype == "table" and rng.random() < 0.5:
                element["metadata"] = {
                    "table_ast": {
                        "rows": [
                            {"cells": [{"text": "Col A"}, {"text": "Col B"}]},
                            {"cells": [{"text": "1"}, {"text": "2"}]},
                        ]
                    }
                }
            elements.append(element)
            reading_order += 1

    if rng.random() < 0.25:
        elements.append(
            {
                "id": f"{prefix}-unpaged",
                "type": "paragraph",
                "text": "Unpaged footnote",
                "reading_order": reading_order,
            }
        )

    doc: dict[str, Any] = {
        "pages": [
            {
                "page_number": p,
                "width": width,
                "height": height,
                "element_ids": [
                    e["id"]
                    for e in elements
                    if e.get("id")
                    and (e.get("page_number") == p or e.get("page") == p - 1)
                ],
            }
            for p in range(1, page_count + 1)
        ],
        "elements": elements,
        "summary": {
            "page_count": page_count,
            "element_count": len(elements),
            "element_types": {},
        },
    }
    if not wrap_document:
        return doc
    return {"status": "succeeded", "document": doc}


@pytest.mark.parametrize(
    "policy",
    [FusionPolicy(), FusionPolicy.drbench_v13(), FusionPolicy.drbench_v14()],
    ids=["default", "drbench_v13", "drbench_v14"],
)
def test_seeded_payload_fusion_and_routing_match_core(policy: FusionPolicy) -> None:
    rng = random.Random(612)
    routed_cases = 0
    missing_cases = 0

    for idx in range(120):
        page_count_primary = rng.randint(1, 4)
        page_count_secondary = rng.randint(1, 4)
        zero_based = idx % 4 == 0
        wrap_document = idx % 7 != 0
        primary = _random_payload(
            rng,
            prefix="d",
            page_count=page_count_primary,
            zero_based=zero_based,
            wrap_document=wrap_document,
        )
        secondary = _random_payload(
            rng,
            prefix="m",
            page_count=page_count_secondary,
            zero_based=zero_based,
            wrap_document=wrap_document,
            allow_missing_id=True,
        )

        core_fused = core_fusion.fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
            policy=policy,
        )
        docstruct_fused = docstruct_fusion.fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
            policy=policy,
        )
        assert docstruct_fused == core_fused

        if not wrap_document:
            continue

        evidence_for_core = copy.deepcopy(core_fused["fusion_evidence"]["pages"])
        if idx % 10 == 0:
            evidence_for_core.append(
                {
                    "page_number": page_count_secondary + 2,
                    "stats": {"route": "mineru"},
                }
            )
        evidence_for_docstruct = copy.deepcopy(evidence_for_core)
        core_routed, core_replaced = core_fusion.apply_page_routes(
            primary, secondary, evidence_for_core, secondary_provider="mineru"
        )
        result = docstruct_fusion.route_pages(
            primary, secondary, evidence_for_docstruct, secondary_provider="mineru"
        )
        assert result.payload == core_routed
        assert result.replaced == core_replaced
        assert evidence_for_docstruct == evidence_for_core

        if result.routed_pages:
            routed_cases += 1
        if result.missing_pages:
            missing_cases += 1

    assert routed_cases > 0
    assert missing_cases > 0


def test_edge_cases_match_core_exactly() -> None:
    prose = (
        "Accessibility requires clear document structure, accurate headings, "
        "and reliable reading order across every page of the document."
    )
    primary = {
        "status": "succeeded",
        "document": {
            "pages": [
                {"page_number": 1, "width": 100.0, "height": 200.0, "element_ids": ["p1"]},
                {"page_number": 2, "width": 100.0, "height": 200.0, "element_ids": ["p2"]},
                {"page_number": 3, "width": 100.0, "height": 200.0, "element_ids": ["p3"]},
            ],
            "elements": [
                {"id": "p1", "type": "paragraph", "text": prose, "page": 0, "reading_order": 1},
                {"id": "p2", "type": "paragraph", "text": "Short.", "page": 1, "reading_order": 2},
                {"id": "p3", "type": "paragraph", "text": "Missing on secondary", "page": 2, "reading_order": 3},
            ],
            "summary": {"page_count": 3, "element_count": 3, "element_types": {"paragraph": 3}},
        },
    }
    secondary = {
        "status": "succeeded",
        "document": {
            "pages": [
                {"page_number": 1, "width": 200.0, "height": 400.0, "element_ids": ["s1", "s2"]},
                {"page_number": 2, "width": 200.0, "height": 400.0, "element_ids": ["s3"]},
            ],
            "elements": [
                {"id": "s1", "type": "paragraph", "text": prose, "page": 0, "reading_order": 1},
                {
                    "id": "s2",
                    "type": "table",
                    "text": "",
                    "page": 0,
                    "reading_order": 2,
                    "bbox": [10, 20, 110, 220],
                    "metadata": {
                        "table_ast": {
                            "rows": [{"cells": [{"text": "H1"}, {"text": "H2"}]}]
                        }
                    },
                },
                {"id": "s3", "type": "paragraph", "text": prose, "page": 1, "reading_order": 3},
            ],
            "summary": {"page_count": 2, "element_count": 3, "element_types": {}},
        },
    }

    assert docstruct_fusion.fuse_extraction_payloads(
        primary, secondary, primary_provider="docling", secondary_provider="mineru"
    ) == core_fusion.fuse_extraction_payloads(
        primary, secondary, primary_provider="docling", secondary_provider="mineru"
    )

    # Unwrapped payload (no top-level "document" key)
    unwrapped_primary = {"elements": primary["document"]["elements"]}
    unwrapped_secondary = {"elements": secondary["document"]["elements"]}
    assert docstruct_fusion.fuse_extraction_payloads(
        unwrapped_primary,
        unwrapped_secondary,
        primary_provider="docling",
        secondary_provider="mineru",
    ) == core_fusion.fuse_extraction_payloads(
        unwrapped_primary,
        unwrapped_secondary,
        primary_provider="docling",
        secondary_provider="mineru",
    )

    # Routing with float page_number (2.0) and a missing secondary page (3)
    evidence_core = [
        {"page_number": 1, "stats": {"route": "docling"}},
        {"page_number": 2.0, "stats": {"route": "mineru"}},
        {"page_number": 3, "stats": {"route": "mineru"}},
    ]
    evidence_docstruct = copy.deepcopy(evidence_core)

    core_payload, core_replaced = core_fusion.apply_page_routes(
        primary, secondary, evidence_core, secondary_provider="mineru"
    )
    route_result = docstruct_fusion.route_pages(
        primary, secondary, evidence_docstruct, secondary_provider="mineru"
    )
    assert route_result.payload == core_payload
    assert route_result.replaced == core_replaced
    assert route_result.missing_pages == (3,)
    assert evidence_docstruct == evidence_core


def test_pure_python_fallback_is_bit_identical_to_core_rapidfuzz(monkeypatch) -> None:
    monkeypatch.setattr(docstruct_fusion, "_rapidfuzz_fuzz", None)

    # Minimal 4-decimal half-rounding boundary where naive 2*lcs/total diverges.
    boundary_primary = {
        "document": {"elements": [{"type": "paragraph", "text": "a" * 3 + "b" * 157, "page_number": 1}]}
    }
    boundary_secondary = {
        "document": {"elements": [{"type": "paragraph", "text": "a" * 3 + "c" * 157, "page_number": 1}]}
    }
    assert docstruct_fusion.fuse_extraction_payloads(
        boundary_primary,
        boundary_secondary,
        primary_provider="docling",
        secondary_provider="mineru",
    ) == core_fusion.fuse_extraction_payloads(
        boundary_primary,
        boundary_secondary,
        primary_provider="docling",
        secondary_provider="mineru",
    )

    rng = random.Random(2026)
    for _ in range(40):
        primary = _random_payload(rng, prefix="d", page_count=2)
        secondary = _random_payload(rng, prefix="m", page_count=2)
        assert docstruct_fusion.fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
        ) == core_fusion.fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
        )
