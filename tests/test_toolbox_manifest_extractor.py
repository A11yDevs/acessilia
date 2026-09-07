"""Testes para o ToolboxManifestExtractor.

Valida que a extração remota via Toolbox produz um ProcessingManifest válido
compatível com o pipeline PDDL.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.manifest.toolbox_extractor import (
    ToolboxExtraction,
    ToolboxManifestExtractor,
)
from backend.tools.toolbox_client import ToolboxClient


FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"


SAMPLE_TOOLBOX_RESPONSE = {
    "status": "succeeded",
    "capability": "document.structure.extract",
    "provider": "docling",
    "document": {
        "elements": [
            {
                "id": "element-000001",
                "type": "heading",
                "raw_label": "heading",
                "reading_order": 1,
                "hierarchy_level": 1,
                "text": "Introdução à Programação Orientada a Objetos",
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
                "id": "element-000002",
                "type": "paragraph",
                "raw_label": "paragraph",
                "reading_order": 2,
                "hierarchy_level": 0,
                "text": "Este é um parágrafo de exemplo.",
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
        "pages": [
            {
                "page_number": 1,
                "width": 595,
                "height": 842,
                "element_ids": ["element-000001", "element-000002"],
            }
        ],
    },
    "provenance": {
        "duration_ms": 1500,
        "provider_version": "1.32.0",
        "cache_key": "cache:sha256:abc123",
    },
}


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=ToolboxClient)
    client.base_url = "http://localhost:8002"
    client.provider = "docling"
    return client


def test_extract_returns_toolbox_extraction(mock_client):
    """Verifica que extract() retorna um ToolboxExtraction com dados corretos."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
    mock_client.upload_artifact = AsyncMock(return_value="sha256:abc123")

    extractor = ToolboxManifestExtractor(
        client=mock_client,
        use_artifact_store=True,
        use_remote_cache=True,
    )
    result = extractor.extract(FIXTURE_PDF)

    assert isinstance(result, ToolboxExtraction)
    assert result.document["status"] == "succeeded"
    assert result.version == "1.32.0"
    assert result.artifact_id == "sha256:abc123"
    assert result.cache_key == "cache:sha256:abc123"
    assert result.configuration["remote_services"] is True
    assert result.configuration["toolbox_base_url"] == "http://localhost:8002"
    assert result.configuration["use_artifact_store"] is True
    assert result.configuration["use_remote_cache"] is True


def test_extract_without_artifact_store_skips_upload(mock_client):
    """Quando use_artifact_store=False, não chama upload."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)

    extractor = ToolboxManifestExtractor(
        client=mock_client,
        use_artifact_store=False,
    )
    result = extractor.extract(FIXTURE_PDF)

    mock_client.upload_artifact.assert_not_called()
    assert result.artifact_id is None


def test_extract_raises_file_not_found(mock_client):
    """Arquivo inexistente levanta FileNotFoundError."""
    extractor = ToolboxManifestExtractor(client=mock_client)
    with pytest.raises(FileNotFoundError):
        extractor.extract(Path("/nonexistent/file.pdf"))


def test_extract_preserves_configuration(mock_client):
    """Configuração do extractor é propagada para ToolboxExtraction."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)

    extractor = ToolboxManifestExtractor(
        client=mock_client,
        enable_ocr=False,
        use_artifact_store=False,
        use_remote_cache=False,
    )
    result = extractor.extract(FIXTURE_PDF)

    assert result.configuration["ocr"] is False
    assert result.configuration["use_artifact_store"] is False
    assert result.configuration["use_remote_cache"] is False


def test_extract_duration_and_timestamps(mock_client):
    """duration_ms e timestamps são preenchidos."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)

    extractor = ToolboxManifestExtractor(client=mock_client, use_artifact_store=False)
    result = extractor.extract(FIXTURE_PDF)

    assert result.duration_ms >= 0
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.completed_at >= result.started_at