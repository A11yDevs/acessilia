"""Regression checks for the backend/docstruct extraction bridge."""
import fitz

from backend.config.settings import settings
from backend.tools import region_extractor as regions
from docstruct.types import Region


def test_blank_page_keeps_unknown_region():
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=300)
        [region] = regions.extract_regions(page)
        assert (region.type, region.bbox, region.page_num) == (
            "unknown", (0, 0, 200, 300), 1,
        )


def test_extraction_preserves_list_and_reading_order():
    with fitz.open() as pdf:
        page = pdf.new_page(width=300, height=300)
        page.insert_text((20, 40), "- First list item")
        page.insert_text((20, 90), "Ordinary paragraph text")
        result = regions.extract_regions(page)
        text_regions = [region for region in result if region.type == "text"]
        assert [region.text for region in text_regions] == [
            "- First list item", "Ordinary paragraph text",
        ]
        assert text_regions[0].metadata["subtype"] == "list"
        assert text_regions[1].metadata["subtype"] == ""
        assert [region.bbox[1] for region in result] == sorted(
            region.bbox[1] for region in result
        )


def test_configured_long_callout_title_is_preserved(monkeypatch):
    title = "A configured callout title " * 5
    monkeypatch.setattr(settings, "callout_known_titles", title)
    region = Region(bbox=(0, 0, 100, 50), type="text", text=title,
                    image_bytes=None, confidence=1.0, page_num=1,
                    metadata={"line_count": 3})
    assert regions._extract_callout_title(region) == title.strip()
