"""The fusion role of a manifest element (#402).

Characterization of the orchestrator's ``_element_role``, written on develop
before it moved to docstruct. The block adapter, the page-number position and
the furniture tests read it.
"""

from __future__ import annotations

import pytest

from backend.agents.pddl_orchestrator import _element_role
from tests.pddl_support import build_element


@pytest.mark.parametrize(
    ("kind", "metadata", "expected"),
    [
        pytest.param("page_header", {}, "header", id="header-type"),
        pytest.param("page_footer", {}, "footer", id="footer-type"),
        pytest.param("paragraph", {}, None, id="body-type"),
        pytest.param("heading", {}, None, id="heading-type"),
        pytest.param("paragraph", {"role": "page_number"}, "page_number", id="metadata-role"),
        pytest.param("page_footer", {"role": "body"}, "body", id="metadata-wins"),
        pytest.param("page_header", {"role": ""}, "header", id="empty-role-falls-back"),
        pytest.param("page_footer", {"role": None}, "footer", id="none-role-falls-back"),
        pytest.param("paragraph", {"role": 0}, None, id="falsy-role-falls-back"),
    ],
)
def test_element_role(kind, metadata, expected) -> None:
    assert _element_role(build_element("e", kind, metadata=metadata)) == expected


def test_the_raw_label_is_not_read() -> None:
    element = build_element("e", "paragraph")
    element.raw_label = "page_footer"

    assert _element_role(element) is None
