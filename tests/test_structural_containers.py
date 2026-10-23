"""Unknown group nodes without a region get no review-structure obligation.

The Toolbox maps Docling's ``key_value_area`` group to ``unknown``. In 006.pdf
four such nodes, each the parent of one paragraph and without provenance,
became review-structure obligations that region inspection cannot render, and
their escalation failed the whole job.
"""

from __future__ import annotations

from backend.core.manifest.builder import _derive_processing_needs
from backend.core.manifest.models import BoundingBox, Provenance
from backend.tools.logger import logger
from tests.pddl_support import build_element


def _key_value_group(element_id: str = "element-000110"):
    group = build_element(element_id, "unknown", text="group")
    group.raw_label = "key_value_area"
    group.page_number = None
    return group


def _child(parent_id: str, element_id: str = "element-000111"):
    child = build_element(element_id, "paragraph", text="Nome: Fulano", reading_order=2)
    child.parent_id = parent_id
    return child


def _review_targets(elements) -> list[str]:
    _, obligations = _derive_processing_needs(elements)
    return [
        target
        for obligation in obligations
        if obligation.kind == "review-structure"
        for target in obligation.target_ids
    ]


def test_a_group_without_a_region_is_not_reviewed():
    group = _key_value_group()
    messages: list[str] = []
    sink = logger.add(messages.append, level="DEBUG", format="{message}")
    try:
        observations, obligations = _derive_processing_needs([group, _child(group.id)])
    finally:
        logger.remove(sink)

    assert not obligations
    assert not observations
    # The skip leaves a trail naming the node.
    assert any(group.id in message and "key_value_area" in message for message in messages)


def test_the_children_of_a_skipped_group_keep_their_obligations():
    group = _key_value_group()
    picture = build_element("element-000111", "picture", reading_order=2)
    picture.parent_id = group.id

    _, obligations = _derive_processing_needs([group, picture])

    assert [(o.kind, o.target_ids) for o in obligations] == [
        ("describe-image", [picture.id])
    ]


def test_an_unknown_leaf_is_still_reviewed():
    leaf = _key_value_group()

    assert _review_targets([leaf]) == [leaf.id]


def test_an_unknown_parent_with_a_region_is_still_reviewed():
    group = _key_value_group()
    group.page_number = 1
    group.provenance = [
        Provenance(
            page_number=1,
            bbox=BoundingBox(left=0, top=0, right=10, bottom=10, coord_origin="TOPLEFT"),
        )
    ]

    assert _review_targets([group, _child(group.id)]) == [group.id]
