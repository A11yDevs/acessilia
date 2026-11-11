"""A document element's fusion role (docstruct.fusion.noise.element_role).

Moved from the core's PDDL payload (#402); the core covers it on its own
models in tests/test_pddl_element_role.py. Here it runs on docstruct's
``DocumentElement``.
"""

from __future__ import annotations

import pytest

from docstruct.fusion.noise import DECOR_TYPES, element_role
from docstruct.manifest import DocumentElement


def _element(kind: str, metadata=None) -> DocumentElement:
    return DocumentElement(id="e", type=kind, raw_label=kind, reading_order=1, hierarchy_level=1,
                           metadata=metadata or {})


@pytest.mark.parametrize(("kind", "role"), sorted(DECOR_TYPES.items()))
def test_a_furniture_type_gives_its_role(kind, role) -> None:
    assert element_role(_element(kind)) == role


@pytest.mark.parametrize(
    ("kind", "metadata", "expected"),
    [("paragraph", {}, None), ("paragraph", {"role": "footer"}, "footer"),
     ("page_header", {"role": "body"}, "body"), ("page_footer", {"role": ""}, "footer")],
)
def test_a_set_metadata_role_wins(kind, metadata, expected) -> None:
    assert element_role(_element(kind, metadata)) == expected
