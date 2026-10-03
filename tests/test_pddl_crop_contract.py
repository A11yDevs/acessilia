"""Behavioral checks run before and after the document crop optimization."""

import asyncio
import hashlib
import multiprocessing
from datetime import datetime, timezone

import pymupdf
import pytest

from backend.agents import pddl_orchestrator as pipeline
from backend.agents.output_schemas import DataOutput, VisionOutput
from backend.core.manifest.models import (
    BoundingBox, ExtractorRun, ManifestElement, ManifestSummary, PageDescriptor,
    ProcessingManifest, Provenance, SourceDocument,
)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "regions.pdf"
    with pymupdf.open() as document:
        for width, height, color in ((200, 120, (1, 0, 0)), (180, 100, (0, 0, 1))):
            page = document.new_page(width=width, height=height)
            page.draw_rect(page.rect, color=color, fill=color)
            page.draw_rect(pymupdf.Rect(20, 30, 80, 90), color=(0, 1, 0), fill=(0, 1, 0))
        document.save(path)
    return path


def element(index, *, kind="picture", page=1, box=None, origin="TOPLEFT", text=None):
    provenance = []
    if page is not None:
        bbox = None if box is None else BoundingBox(
            left=box[0], top=box[1], right=box[2], bottom=box[3], coord_origin=origin,
        )
        provenance = [Provenance(page_number=page, bbox=bbox)]
    return ManifestElement(
        id=f"element-{index}", type=kind, raw_label=kind, reading_order=index,
        hierarchy_level=0, page_number=page, provenance=provenance, text=text,
    )


def manifest(source, elements):
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    return ProcessingManifest(
        manifest_id="crop-contract", created_at=now, title="Crop contract", language="pt-BR",
        source=SourceDocument(
            document_id="source", filename=source.name, path=str(source),
            media_type="application/pdf", byte_size=source.stat().st_size,
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        ),
        extractor=ExtractorRun(version="test", started_at=now, completed_at=now,
                               duration_ms=0, configuration={}),
        pages=[PageDescriptor(page_number=number, element_ids=[
            item.id for item in elements if item.page_number == number
        ]) for number in (1, 2)],
        elements=elements,
        summary=ManifestSummary(page_count=2, element_count=len(elements),
                                observation_count=0, obligation_count=0, element_types={}),
    )


def pixels(png):
    bitmap = pymupdf.Pixmap(png)
    return bitmap.width, bitmap.height, bitmap.n, bitmap.samples


def expected_pixels(source, page_number, rectangle):
    with pymupdf.open(source) as document:
        page = document[page_number - 1]
        bitmap = page.get_pixmap(clip=pymupdf.Rect(rectangle), dpi=160, alpha=False)
        return bitmap.width, bitmap.height, bitmap.n, bitmap.samples


@pytest.mark.parametrize("page, box, origin, fallback, rectangle", [
    (1, (20, 30, 80, 90), "TOPLEFT", None, (20, 30, 80, 90)),
    (1, (20, 90, 80, 30), "BOTTOMLEFT", None, (20, 30, 80, 90)),
    (1, (80, 90, 20, 30), "UNKNOWN", None, (20, 30, 80, 90)),
    (1, (-10, -10, 40, 40), "TOPLEFT", None, (0, 0, 40, 40)),
    (1, (10, 10, 12, 12), "TOPLEFT", None, (0, 0, 200, 120)),
    (1, (300, 300, 400, 400), "TOPLEFT", None, (0, 0, 200, 120)),
    (1, None, "TOPLEFT", None, (0, 0, 200, 120)),
    (None, None, "TOPLEFT", 2, (0, 0, 180, 100)),
])
def test_crop_geometry_and_pixels(source, page, box, origin, fallback, rectangle):
    item = element(1, page=page, box=box, origin=origin)
    png, actual_page = pipeline._extract_picture_bytes(source, item, fallback)
    assert actual_page == (page or fallback)
    assert pixels(png) == expected_pixels(source, actual_page, rectangle)


def test_crop_missing_page_and_bad_inputs(source, tmp_path):
    assert pipeline._extract_picture_bytes(source, element(1, page=3), None) == (None, 3)
    assert pipeline._extract_picture_bytes(tmp_path / "missing.pdf", element(1, page=None), None) == (None, 0)
    with pytest.raises(RuntimeError, match="no such file"):
        pipeline._extract_picture_bytes(tmp_path / "missing.pdf", element(1), None)


@pytest.mark.asyncio
async def test_enrichment_preserves_pngs_provider_order_and_metadata(source, monkeypatch):
    items = [element(1, box=(20, 30, 80, 90)), element(2, page=2),
             element(3, kind="table", box=(20, 30, 80, 90))]
    document = manifest(source, items)
    expected = [expected_pixels(source, 1, (20, 30, 80, 90)),
                expected_pixels(source, 2, (0, 0, 180, 100)),
                expected_pixels(source, 1, (20, 30, 80, 90))]
    calls = []

    class Vision:
        def __init__(self, **kwargs):
            assert kwargs == {"mode": "detalhado"}

        async def describe_region(self, **kwargs):
            calls.append(("vision", kwargs["page_num"], pixels(kwargs["image_bytes"])))
            assert kwargs["mode"] == "detalhado"
            assert kwargs["total_pages"] == 2
            return VisionOutput(kind="description", description=f"Image on page {kwargs['page_num']}",
                                language="pt-BR", confidence=0.9, warnings=["source warning"],
                                mentioned_elements=["green region"])

    class Data:
        async def process_region(self, **kwargs):
            calls.append(("data", kwargs["page_num"], pixels(kwargs["image_bytes"])))
            assert kwargs["classification"] == "table"
            return DataOutput(kind="table", language="pt-BR", confidence=0.8,
                              rows=[{"cells": [{"text": "A", "scope": "col"}, {"text": "B"}]},
                                    {"cells": [{"text": "1"}, {"text": ""}]}], warnings=["table warning"])

    monkeypatch.setattr(pipeline, "VisionAgent", Vision)
    monkeypatch.setattr(pipeline, "DataAgent", Data)
    await pipeline._enrich_picture_descriptions(document, source, mode="detalhado")
    await pipeline._enrich_table_structures(document, source)

    assert calls == [("vision", 1, expected[0]), ("vision", 2, expected[1]), ("data", 1, expected[2])]
    assert [item.text for item in items[:2]] == ["Image on page 1", "Image on page 2"]
    assert items[0].metadata["vision_warnings"] == ["source warning"]
    assert items[0].metadata["vision_confidence"] == 0.9
    assert items[2].metadata["table_column_count"] == 2
    assert items[2].metadata["table_has_header"] is True
    assert items[2].metadata["table_ast"]["body"][1]["cells"][1]["text"] == ""
    assert items[2].metadata["data_warnings"] == ["table warning"]


@pytest.mark.asyncio
async def test_enrichment_cancellation_does_not_apply_unfinished_results(source, monkeypatch):
    items = [element(1), element(2)]
    document = manifest(source, items)
    started = asyncio.Event()
    children_before = {child.pid for child in multiprocessing.active_children()}

    class Vision:
        def __init__(self, **kwargs):
            pass

        async def describe_region(self, **kwargs):
            started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(pipeline, "VisionAgent", Vision)
    task = asyncio.create_task(pipeline._enrich_picture_descriptions(document, source, mode="medio"))
    await asyncio.wait_for(started.wait(), timeout=15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(item.text is None and item.metadata == {} for item in items)
    assert {child.pid for child in multiprocessing.active_children()} == children_before
