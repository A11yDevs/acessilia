"""Testes para o ToolboxStructurer (pipeline legacy).

Valida que a extração remota via Toolbox produz Regions compatíveis
com o pipeline legacy e que o fallback PyMuPDF funciona em falha.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz
import pytest

from backend.tools.region_extractor import Region
from backend.tools.toolbox_structurer import ToolboxStructurer
from backend.tools.toolbox_client import ToolboxClient, ToolboxProviderUnavailable


FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"


SAMPLE_TOOLBOX_RESPONSE = {
    "status": "succeeded",
    "capability": "document.structure.extract",
    "provider": "docling",
    "document": {
        "elements": [
            {
                "type": "heading",
                "text": "Introdução",
                "page_number": 1,
                "confidence": 0.95,
                "provenance": [
                    {
                        "page_number": 1,
                        "bbox": {"left": 72, "top": 50, "right": 523, "bottom": 80},
                    }
                ],
            },
            {
                "type": "paragraph",
                "text": "Conteúdo do parágrafo.",
                "page_number": 1,
                "confidence": 0.90,
                "provenance": [
                    {
                        "page_number": 1,
                        "bbox": {"left": 72, "top": 90, "right": 523, "bottom": 120},
                    }
                ],
            },
        ],
        "pages": [{"page_number": 1, "width": 595, "height": 842}],
    },
    "provenance": {"duration_ms": 1500, "provider_version": "1.32.0"},
}


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=ToolboxClient)
    client.base_url = "http://localhost:8002"
    client.provider = "docling"
    return client


def test_extract_page_regions_returns_regions(mock_client):
    """ToolboxStructurer.extract_page_regions retorna Regions ordenadas."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)

    structurer = ToolboxStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    assert len(regions) == 2
    assert all(isinstance(r, Region) for r in regions)
    assert regions[0].type == "heading"
    assert regions[1].type == "paragraph"
    assert regions[0].page_num == 1
    assert regions[1].page_num == 1
    # Ordenados por top (y)
    assert regions[0].bbox[1] < regions[1].bbox[1]


def test_extract_page_regions_empty_page_fallback(mock_client):
    """Página sem elementos recebe Region unknown com toolbox_empty=True."""
    empty_response = {
        "status": "succeeded",
        "capability": "document.structure.extract",
        "provider": "docling",
        "document": {"elements": [], "pages": [{"page_number": 1}]},
        "provenance": {"duration_ms": 100, "provider_version": "1.32.0"},
    }
    mock_client.extract_structure = AsyncMock(return_value=empty_response)

    structurer = ToolboxStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    assert len(regions) == 1
    assert regions[0].type == "unknown"
    assert regions[0].metadata.get("toolbox_empty") is True


def test_fallback_on_provider_unavailable(mock_client):
    """Se Toolbox está indisponível, cai em PyMuPDF (extract_regions)."""
    mock_client.extract_structure = AsyncMock(
        side_effect=ToolboxProviderUnavailable("offline")
    )

    structurer = ToolboxStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    # PyMuPDF sempre retorna ao menos uma Region
    assert len(regions) >= 1
    # Todas as regions têm page_num
    assert all(r.page_num == 1 for r in regions)


def test_cache_prevents_second_call(mock_client):
    """Segunda chamada para o mesmo documento usa cache em memória."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)

    structurer = ToolboxStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]

    # Primeira chamada
    structurer.extract_page_regions(page)
    # Segunda chamada — deve usar cache
    structurer.extract_page_regions(page)

    doc.close()

    # extract_structure deve ter sido chamado apenas uma vez
    assert mock_client.extract_structure.call_count == 1


def test_region_metadata_contains_source_toolbox(mock_client):
    """Regions da Toolbox têm metadata.source='toolbox'."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)

    structurer = ToolboxStructurer(client=mock_client)

    doc = fitz.open(FIXTURE_PDF)
    page = doc[0]
    regions = structurer.extract_page_regions(page)
    doc.close()

    for r in regions:
        assert r.metadata.get("source") == "toolbox"