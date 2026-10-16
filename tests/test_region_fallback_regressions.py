"""Exercise real PDF regions and the full gap-filling entry point."""
import io
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image

from backend.tools.region_extractor import extract_regions, _fill_gaps_with_unknown, crop_region_to_image
from docstruct.regions.grouping import _fill_gaps_with_unknown as fill_library_gaps
from docstruct.types import Region


@pytest.mark.parametrize('fill', [_fill_gaps_with_unknown, fill_library_gaps])
@pytest.mark.parametrize('boxes', [
    [(0, 0, 60, 200), (140, 0, 200, 200)],
    [(100, 0, 200, 100), (0, 40, 60, 150)],
])
def test_gap_filling_preserves_uncovered_columns_without_covering_text(fill, boxes):
    regions = [Region(box, 'text', 'body', None, 1, 1) for box in boxes]
    fill(SimpleNamespace(rect=SimpleNamespace(width=200, height=200)), regions, 1)
    gaps = [r for r in regions if r.type == 'unknown']
    assert any(r.bbox[0] <= 80 < r.bbox[2] and r.bbox[1] <= 80 < r.bbox[3] for r in gaps)
    for gap in gaps:
        x0, y0, x1, y1 = gap.bbox
        assert all(not (c[0] < x1 and c[2] > x0 and c[1] < y1 and c[3] > y0)
                   for c in boxes)


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_region_fallback_retains_exact_images_and_rotated_positions(rotation):
    with fitz.open() as pdf:
        page = pdf.new_page(width=240, height=160)
        expected = []
        for color, box in [('red', (10, 30, 60, 80)), ('blue', (150, 70, 200, 120))]:
            image = Image.new('RGB', (50, 50), color)
            stream = io.BytesIO()
            image.save(stream, format='PNG')
            page.insert_image(fitz.Rect(box), stream=stream.getvalue())
            expected.append((box, image.getpixel((0, 0))))
        page.insert_text((10, 15), 'Header')
        page.set_rotation(rotation)
        regions = extract_regions(page)
        images = [r for r in regions if r.type == 'image']
        assert len(images) == 2
        for box, color in expected:
            rotated = tuple(fitz.Rect(box) * page.rotation_matrix)
            region = next(r for r in images if r.bbox == pytest.approx(rotated))
            assert Image.open(io.BytesIO(region.image_bytes)).convert('RGB').getpixel((0, 0)) == color
            crop = Image.open(io.BytesIO(crop_region_to_image(page, region.bbox, dpi=72))).convert('RGB')
            assert crop.getpixel((crop.width // 2, crop.height // 2)) == color
        for region in regions:
            x0, y0, x1, y1 = region.bbox
            assert 0 <= x0 <= x1 <= page.rect.width
            assert 0 <= y0 <= y1 <= page.rect.height
