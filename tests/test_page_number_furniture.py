"""Page numbers stay out of the delivered body (issue #262).

Boxes follow acessilia-dataset case 036 (``velocidade-instantanea.pdf``): a
US Letter page in PDF points, origin at the bottom left, with the page number
centered in the bottom margin.
"""

from __future__ import annotations

from backend.agents.pddl_orchestrator import _manifest_pages_to_payload
from backend.core.manifest.models import BoundingBox, Provenance
from tests.pddl_support import build_element, build_manifest

WIDTH, HEIGHT = 612.0, 792.0
#: Bottom margin, where case 036 prints its page numbers.
FOOTER_BOX = (295.8, 48.9, 301.6, 37.5)
#: Middle of the page, where a standalone number is body content.
BODY_BOX = (295.8, 400.0, 301.6, 388.6)


def _placed(element_id, element_type, text, box, *, metadata=None, reading_order=1):
    element = build_element(
        element_id, element_type, text=text, metadata=metadata, reading_order=reading_order
    )
    left, top, right, bottom = box
    element.provenance = [
        Provenance(
            page_number=1,
            bbox=BoundingBox(
                left=left, top=top, right=right, bottom=bottom, coord_origin="BOTTOMLEFT"
            ),
        )
    ]
    return element


def _delivered_texts(*elements):
    manifest = build_manifest(list(elements), [])
    manifest.pages[0].width, manifest.pages[0].height = WIDTH, HEIGHT
    [page] = _manifest_pages_to_payload(manifest)
    return [
        block.get("text") or (block.get("items") or [None])[0] or block.get("rows")
        for block in page["blocks"]
    ]


BODY = _placed("element-body", "paragraph", "Body text.", (72, 700, 540, 600))


def test_page_footer_number_is_left_out():
    footer = _placed("element-footer", "page_footer", "1", FOOTER_BOX, reading_order=2)

    assert _delivered_texts(BODY, footer) == ["Body text."]


def test_furniture_layer_number_is_left_out_whatever_its_type():
    footer = _placed(
        "element-footer", "paragraph", "2", BODY_BOX,
        metadata={"content_layer": "furniture"}, reading_order=2,
    )

    assert _delivered_texts(BODY, footer) == ["Body text."]


def test_paragraph_number_in_the_margin_is_left_out():
    footer = _placed("element-footer", "paragraph", "iv", FOOTER_BOX, reading_order=2)

    assert _delivered_texts(BODY, footer) == ["Body text."]


def test_standalone_number_in_the_body_is_kept():
    number = _placed("element-number", "paragraph", "3", BODY_BOX, reading_order=2)

    assert _delivered_texts(BODY, number) == ["Body text.", "3"]


def test_list_item_number_in_the_margin_is_kept():
    item = _placed("element-item", "list_item", "4", FOOTER_BOX, reading_order=2)

    assert _delivered_texts(BODY, item) == ["Body text.", "4"]


def test_page_header_text_is_kept():
    header = _placed(
        "element-header", "page_header", "University of Brasilia", (117, 722, 241, 711),
        reading_order=2,
    )

    assert _delivered_texts(BODY, header) == ["Body text.", "University of Brasilia"]


def test_number_without_position_is_kept():
    number = build_element("element-number", "paragraph", text="5", reading_order=2)

    assert _delivered_texts(BODY, number) == ["Body text.", "5"]
