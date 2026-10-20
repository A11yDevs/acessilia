"""OrientedBox keeps the origin of its y axis through every conversion."""
import pytest

from docstruct.geometry import OrientedBox, is_bottom_left


@pytest.mark.parametrize(
    ("origin", "top", "bottom", "expected"),
    [
        ("BOTTOMLEFT", 10.0, 20.0, True),
        ("bottomleft", 10.0, 20.0, True),
        ("TOPLEFT", 20.0, 10.0, False),
        ("UNKNOWN", 20.0, 10.0, True),
        ("UNKNOWN", 10.0, 20.0, False),
        ("UNKNOWN", 10.0, 10.0, False),
        (None, 20.0, 10.0, True),
        ("", 10.0, 20.0, False),
    ],
)
def test_is_bottom_left(origin, top, bottom, expected):
    assert is_bottom_left(origin, top, bottom) is expected


# The same box on a 600 x 800 page, stored in each frame.
TOP_LEFT = OrientedBox(60, 80, 300, 160, "TOPLEFT")
BOTTOM_LEFT = OrientedBox(60, 720, 300, 640, "BOTTOMLEFT")
UNKNOWN_UP = OrientedBox(60, 720, 300, 640, "UNKNOWN")
UNKNOWN_DOWN = OrientedBox(60, 80, 300, 160)


def test_top_down_mirrors_bottom_left_boxes():
    assert TOP_LEFT.top_down() == (60, 80, 300, 160)
    assert UNKNOWN_DOWN.top_down() == (60, 80, 300, 160)
    assert BOTTOM_LEFT.top_down() == (60, -720, 300, -640)
    assert UNKNOWN_UP.top_down() == (60, -720, 300, -640)


def test_top_down_keeps_the_vertical_order_of_boxes():
    higher = OrientedBox(0, 700, 10, 690, "BOTTOMLEFT").top_down()
    lower = OrientedBox(0, 100, 10, 90, "BOTTOMLEFT").top_down()
    assert higher[1] < lower[1]


@pytest.mark.parametrize("box", [TOP_LEFT, BOTTOM_LEFT, UNKNOWN_UP, UNKNOWN_DOWN])
def test_page_fractions_agree_in_every_frame(box):
    assert box.page_fractions(600.0, 800.0) == pytest.approx((0.1, 0.1, 0.5, 0.2))


@pytest.mark.parametrize("size", [(None, 800.0), (600.0, None), (0.0, 800.0), (600.0, 0.0)])
def test_page_fractions_need_a_page_size(size):
    assert TOP_LEFT.page_fractions(*size) is None


def test_boxes_are_values():
    assert OrientedBox(1, 2, 3, 4, "TOPLEFT") == OrientedBox(1, 2, 3, 4, "TOPLEFT")
    with pytest.raises(AttributeError):
        TOP_LEFT.left = 0  # type: ignore[misc]
