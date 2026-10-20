"""order_reading_items: the processing manifest's reading order (#203)."""
import pytest

from docstruct.geometry import OrientedBox, ReadingItem, order_reading_items, reading_role

PAGE_HEIGHT = 800.0


def item(key, box=None, *, role="body", page=1, rank=1, origin="TOPLEFT"):
    oriented = None
    if box is not None:
        left, top, right, bottom = box
        if origin == "BOTTOMLEFT":
            top, bottom = PAGE_HEIGHT - top, PAGE_HEIGHT - bottom
        oriented = OrientedBox(left, top, right, bottom, origin)
    return ReadingItem(key=key, page=page, role=role, box=oriented, rank=rank)


@pytest.mark.parametrize(
    ("element_type", "raw_label", "expected"),
    [
        ("group", "group", "group"),
        ("paragraph", "group", "body"),
        ("page_header", "text", "header"),
        ("paragraph", "Header", "header"),
        ("page_footer", "text", "footer"),
        ("paragraph", "page_number", "footer"),
        ("page_header", "page_footer", "header"),
        ("paragraph", "text", "body"),
    ],
)
def test_reading_role(element_type, raw_label, expected):
    assert reading_role(element_type, raw_label) == expected


def two_columns(origin):
    rows = [
        ("b2", (320, 460, 580, 500)),
        ("a1", (20, 100, 280, 140)),
        ("title", (20, 40, 580, 80)),
        ("figure", (20, 300, 580, 420)),
        ("b1", (320, 100, 580, 140)),
        ("a2", (20, 160, 280, 200)),
        ("a3", (20, 460, 280, 500)),
        ("b0", (320, 160, 580, 200)),
    ]
    return [item(key, box, rank=n, origin=origin) for n, (key, box) in enumerate(rows, 1)]


@pytest.mark.parametrize("origin", ["TOPLEFT", "BOTTOMLEFT"])
def test_columns_between_banners(origin):
    assert order_reading_items(two_columns(origin)) == [
        "title", "a1", "a2", "b1", "b0", "figure", "a3", "b2",
    ]


def test_roles_order_a_page():
    items = [
        item("footer", (20, 760, 580, 780), role="footer", rank=1),
        item("body", (20, 100, 580, 140), rank=2),
        item("header", (20, 10, 580, 30), role="header", rank=3),
        item("group", (20, 600, 580, 700), role="group", rank=4),
    ]
    assert order_reading_items(items) == ["group", "header", "body", "footer"]


def test_pages_in_order_and_pageless_items_first():
    items = [
        item("p2", (20, 100, 580, 140), page=2),
        item("doc", None, page=None, role="group"),
        item("p1-b", (20, 200, 580, 240), page=1, rank=1),
        item("p1-a", (20, 100, 580, 140), page=1, rank=2),
    ]
    assert order_reading_items(items) == ["doc", "p1-a", "p1-b", "p2"]


def test_ties_keep_the_incoming_rank():
    items = [item(key, (20, 100, 580, 140), rank=rank) for key, rank in (("b", 2), ("a", 1))]
    assert order_reading_items(items) == ["a", "b"]


def test_known_defect_bottom_left_columns_without_a_banner_keep_input_order():
    """Frozen for parity with the manifest builder; a fix is a separate change."""
    rows = [("b1", (320, 100, 580, 140)), ("a1", (20, 100, 280, 140)),
            ("b2", (320, 160, 580, 200)), ("a2", (20, 160, 280, 200))]
    top_left = [item(k, b, rank=n) for n, (k, b) in enumerate(rows, 1)]
    bottom_left = [item(k, b, rank=n, origin="BOTTOMLEFT") for n, (k, b) in enumerate(rows, 1)]

    assert order_reading_items(top_left) == ["a1", "a2", "b1", "b2"]
    assert order_reading_items(bottom_left) == ["b1", "a1", "b2", "a2"]


def test_nothing_to_order():
    assert order_reading_items([]) == []
