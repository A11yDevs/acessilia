"""Testes para o ToolboxLayoutStructurer (document.layout.analyze).

Valida que a análise de layout via Toolbox produz Regions classificadas
com tipos semânticos (text_clean, table, formula, etc.) e que o fallback
PyMuPDF funciona em falha.
"""
from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import AsyncMock

import fitz
import pytest

from backend.tools.region_extractor import Region
from backend.tools.toolbox_layout_client import ToolboxLayoutClient
from backend.tools.toolbox_layout_structurer import ToolboxLayoutStructurer

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"

SAMPLE_LAYOUT_RESPONSE = {
    "status": "succeeded",
    "capability": "document.layout.analyze",
    "provider": "docling-layout",
    "document": {
        "page_count": 1,
        "region_count": 4,
        "pages": [
            {
                "page_number": 1,
                "width": 595,
                "height": 842,
                "regions": [
                    {
                        "type": "text_clean",
                        "label": "paragraph",
                        "bbox": [50, 50, 500, 100],
                        "confidence": 0.98,
                        "text": "Primeiro parágrafo.",
                        "page_number": 1,
                    },
                    {
                        "type": "embedded_image",
                        "label": "picture",
                        "bbox": [50, 120, 500, 300],
                        "confidence": 0.85,
                        "text": "",
                        "page_number": 1,
                    },
                    {
                        "type": "table",
                        "label": "table",
                        "bbox": [50, 320, 500, 450],
                        "confidence": 0.95,
                        "text": "Header1|Header2",
                        "page_number": 1,
                    },
                    {
                        "type": "formula",
                        "label": "formula",
                        "bbox": [50, 470, 500, 520],
                        "confidence": 0.90,
                        "text": "E = mc^2",
                        "page_number": 1,
                    },
                ],
            },
        ],
    },
    "provenance": {"duration_ms": 2500, "provider_version": "1.32.0"},
}


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=ToolboxLayoutClient)
    client.base_url = "http://localhost:8002"
    client.provider = "docling-layout"
    return client


def test_extract_page_regions_returns_regions(mock_client):
    """ToolboxLayoutStructurer.extract_page_regions retorna Regions."""
    mock_client.analyze = AsyncMock(return_value=SAMPLE_LAYOUT_RESPONSE)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    assert len(regions) == 4
    assert all(isinstance(r, Region) for r in regions)
    assert all(r.page_num == 1 for r in regions)


def test_regions_have_correct_types(mock_client):
    """Regions são mapeadas corretamente: text_clean→text, table→table, etc."""
    mock_client.analyze = AsyncMock(return_value=SAMPLE_LAYOUT_RESPONSE)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    types = {r.type for r in regions}
    assert "text" in types
    assert "image" in types
    assert "table" in types
    assert "formula" in types


def test_regions_have_layout_metadata(mock_client):
    """Cada Region preserva o layout_type original e source='toolbox-layout'."""
    mock_client.analyze = AsyncMock(return_value=SAMPLE_LAYOUT_RESPONSE)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    for r in regions:
        assert r.metadata.get("source") == "toolbox-layout"
        assert r.metadata.get("layout_type") in (
            "text_clean", "embedded_image", "table", "formula",
        )


def test_regions_ordered_by_top(mock_client):
    """Regions são ordenadas por bbox[1] (top), depois bbox[0] (left)."""
    mock_client.analyze = AsyncMock(return_value=SAMPLE_LAYOUT_RESPONSE)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    for i in range(len(regions) - 1):
        assert regions[i].bbox[1] <= regions[i + 1].bbox[1]


def test_empty_page_returns_unknown_region(mock_client):
    """Página sem regiões recebe Region unknown com toolbox_layout_empty=True."""
    empty = {
        "status": "succeeded",
        "capability": "document.layout.analyze",
        "provider": "docling-layout",
        "document": {
            "page_count": 1,
            "region_count": 0,
            "pages": [{"page_number": 1, "width": 595, "height": 842, "regions": []}],
        },
        "provenance": {"duration_ms": 100, "provider_version": "1.32.0"},
    }
    mock_client.analyze = AsyncMock(return_value=empty)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    assert len(regions) == 1
    assert regions[0].type == "unknown"
    assert regions[0].metadata.get("toolbox_layout_empty") is True


def test_missing_page_returns_unknown_region(mock_client):
    """Página não encontrada na resposta recebe Region unknown."""
    mock_client.analyze = AsyncMock(return_value=SAMPLE_LAYOUT_RESPONSE)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[2]  # página 3 — resposta só tem página 1
    regions = structurer.extract_page_regions(page)
    doc.close()

    assert len(regions) == 1
    assert regions[0].type == "unknown"


def test_fallback_on_exception(mock_client):
    """Se ToolboxLayout lança exceção, cai em PyMuPDF."""
    from backend.tools.toolbox_client import ToolboxProviderUnavailable

    mock_client.analyze = AsyncMock(
        side_effect=ToolboxProviderUnavailable("offline")
    )

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    assert len(regions) >= 1
    assert all(r.page_num == 1 for r in regions)


def test_cache_prevents_second_call(mock_client):
    """Segunda chamada para o mesmo documento usa cache em memória."""
    mock_client.analyze = AsyncMock(return_value=SAMPLE_LAYOUT_RESPONSE)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)

    structurer.extract_page_regions(doc[0])
    structurer.extract_page_regions(doc[0])

    doc.close()

    assert mock_client.analyze.call_count == 1


def test_region_bbox_is_float_tuple(mock_client):
    """Bbox das Regions é uma tupla de 4 floats."""
    mock_client.analyze = AsyncMock(return_value=SAMPLE_LAYOUT_RESPONSE)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    for r in regions:
        assert len(r.bbox) == 4
        assert all(isinstance(v, float) for v in r.bbox)


def test_cache_works_for_same_file_different_page(mock_client):
    """Cache usa o arquivo (não a página), então página diferente não faz nova chamada."""
    mock_client.analyze = AsyncMock(return_value=SAMPLE_LAYOUT_RESPONSE)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)

    structurer.extract_page_regions(doc[0])
    structurer.extract_page_regions(doc[1])

    doc.close()

    # Cache do arquivo evita segunda chamada
    assert mock_client.analyze.call_count == 1


def test_region_without_bbox_is_skipped(mock_client):
    """Região sem bbox é ignorada (None retornado por _raw_region_to_region)."""
    response = copy.deepcopy(SAMPLE_LAYOUT_RESPONSE)
    response["document"]["pages"][0]["regions"] = [
        {"type": "text_clean", "text": "no bbox", "confidence": 0.9},
    ]
    mock_client.analyze = AsyncMock(return_value=response)

    structurer = ToolboxLayoutStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    assert len(regions) == 1  # unknown region because all raw regions were skipped
    assert regions[0].type == "unknown"