"""A logo and the page header lines beside it reach the reader as one paragraph.

Boxes follow acessilia-dataset case 036 (``velocidade-instantanea.pdf``): the
university logo at the top left, with the university and the department on
two page_header lines to its right, above the title.
"""

from __future__ import annotations

from backend.agents.pddl_orchestrator import MSG_LETTERHEAD_TEXT, _manifest_pages_to_payload
from backend.i18n import t
from tests.test_page_number_furniture import FOOTER_BOX, HEIGHT, WIDTH, _placed
from tests.pddl_support import build_manifest

LINE_1_BOX = (117.0, 722.4, 241.4, 711.0)
LINE_2_BOX = (117.0, 705.1, 270.2, 693.7)
LOGO_BOX = (64.3, 723.2, 270.1, 694.0)
#: A picture in the body, below the header band.
BODY_PICTURE_BOX = (72, 500, 300, 400)

FURNITURE = {"content_layer": "furniture"}
BODY = _placed("element-body", "paragraph", "Body text.", (72, 650, 540, 600),
               reading_order=4)


def _letterhead():
    return [
        _placed("line-1", "page_header", "University of Brasilia", LINE_1_BOX,
                metadata=FURNITURE, reading_order=1),
        _placed("logo", "picture", "A long description of the logo.", LOGO_BOX,
                reading_order=2),
        _placed("line-2", "page_header", "Department of Mathematics", LINE_2_BOX,
                metadata=FURNITURE, reading_order=3),
    ]


def _blocks(*elements):
    manifest = build_manifest(list(elements), [])
    manifest.pages[0].width, manifest.pages[0].height = WIDTH, HEIGHT
    [page] = _manifest_pages_to_payload(manifest)
    return page["blocks"]


def test_logo_and_header_lines_become_one_paragraph():
    blocks = _blocks(*_letterhead(), BODY)

    assert [block["type"] for block in blocks] == ["paragraph", "paragraph"]
    letterhead = blocks[0]
    assert letterhead["text"] == t(MSG_LETTERHEAD_TEXT).format(
        lines="University of Brasilia, Department of Mathematics"
    )
    assert "A long description" not in letterhead["text"]
    assert letterhead["metadata"]["role"] == "header"
    assert letterhead["metadata"]["letterhead_members"] == ["line-1", "logo", "line-2"]
    assert blocks[1]["text"] == "Body text."


def test_page_header_without_a_picture_is_unchanged():
    line_1, _, line_2 = _letterhead()

    texts = [block["text"] for block in _blocks(line_1, line_2, BODY)]

    assert texts == ["University of Brasilia", "Department of Mathematics", "Body text."]


def test_picture_away_from_the_header_lines_is_not_merged():
    line_1, _, line_2 = _letterhead()
    picture = _placed("figure", "picture", "A chart.", BODY_PICTURE_BOX, reading_order=5)

    blocks = _blocks(line_1, line_2, BODY, picture)

    assert [block["type"] for block in blocks] == ["paragraph", "paragraph", "paragraph", "image"]
    assert blocks[-1]["alt_text"] == "A chart."


def test_page_number_is_still_left_out_beside_a_letterhead():
    footer = _placed("element-footer", "page_footer", "1", FOOTER_BOX, reading_order=9)

    blocks = _blocks(*_letterhead(), BODY, footer)

    assert len(blocks) == 2
    assert blocks[0]["metadata"]["role"] == "header"
