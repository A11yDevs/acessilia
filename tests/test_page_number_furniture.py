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
#: Top margin (centre y ~ 0.06 of the page).
HEADER_BOX = (295.8, 750.0, 301.6, 738.6)
#: Above the bottom band (centre y ~ 0.85), as a two-line footer sits.
TALL_FOOTER_BOX = (295.8, 125.0, 301.6, 113.6)
#: Middle of the page, where a standalone number is body content.
BODY_BOX = (295.8, 400.0, 301.6, 388.6)


def _placed(
    element_id, element_type, text, box, *, metadata=None, reading_order=1, raw_label=None
):
    element = build_element(
        element_id, element_type, text=text, metadata=metadata, reading_order=reading_order
    )
    element.raw_label = raw_label or element_type
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


def test_furniture_layer_number_in_a_paragraph_is_left_out():
    footer = _placed(
        "element-footer", "paragraph", "2", BODY_BOX,
        metadata={"content_layer": "furniture"}, reading_order=2,
    )

    assert _delivered_texts(BODY, footer) == ["Body text."]


def test_furniture_raw_label_number_above_the_band_is_left_out():
    footer = _placed(
        "element-footer", "paragraph", "6", TALL_FOOTER_BOX,
        raw_label="page_footer", reading_order=2,
    )

    assert _delivered_texts(BODY, footer) == ["Body text."]


def test_decorated_or_repeated_furniture_number_is_left_out():
    header = _placed("element-header", "page_header", "281 281", HEADER_BOX)
    footer = _placed("element-footer", "page_footer", "- 7 -", FOOTER_BOX, reading_order=3)
    body = _placed("element-body", "paragraph", "Body text.", (72, 700, 540, 600), reading_order=2)

    assert _delivered_texts(header, body, footer) == ["Body text."]


def test_furniture_list_item_number_is_kept():
    item = _placed(
        "element-item", "list_item", "4", BODY_BOX,
        metadata={"content_layer": "furniture"}, reading_order=2,
    )

    assert _delivered_texts(BODY, item) == ["Body text.", "4"]


def test_paragraph_number_in_the_bottom_margin_is_left_out():
    footer = _placed("element-footer", "paragraph", "iv", FOOTER_BOX, reading_order=2)

    assert _delivered_texts(BODY, footer) == ["Body text."]


def test_paragraph_number_in_the_top_margin_is_left_out():
    header = _placed("element-header", "paragraph", "3", HEADER_BOX)
    body = _placed("element-body", "paragraph", "Body text.", (72, 700, 540, 600), reading_order=2)

    assert _delivered_texts(header, body) == ["Body text."]


def test_several_numbers_in_the_margin_are_kept():
    """Chart axis labels: a page holds one page number, so none of them is it."""
    labels = [
        _placed(
            f"element-label-{n}", "paragraph", str(n),
            (100.0 * n, 48.9, 100.0 * n + 12, 37.5), reading_order=n + 1,
        )
        for n in (1, 2, 3)
    ]

    assert _delivered_texts(BODY, *labels) == ["Body text.", "1", "2", "3"]


def test_number_in_the_margin_next_to_a_marked_page_number_is_kept():
    marker = _placed("element-marker", "paragraph", "1", HEADER_BOX, reading_order=2)
    footer = _placed("element-footer", "page_footer", "85", FOOTER_BOX, reading_order=3)

    assert _delivered_texts(BODY, marker, footer) == ["Body text.", "1"]


def test_single_uppercase_roman_letter_in_the_margin_is_kept():
    letter = _placed("element-letter", "paragraph", "V", FOOTER_BOX, reading_order=2)

    assert _delivered_texts(BODY, letter) == ["Body text.", "V"]


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
