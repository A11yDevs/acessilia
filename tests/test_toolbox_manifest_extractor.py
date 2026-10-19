"""Testes para o ToolboxManifestExtractor.

Valida que a extração remota via Toolbox produz um ProcessingManifest válido
compatível com o pipeline PDDL.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.core.manifest.toolbox_extractor import (
    ToolboxExtraction,
    ToolboxManifestExtractor,
)
from acessilia_sdk.toolbox.clients import ToolboxArtifactClient, ToolboxStructureClient


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
        "title": "Tutorial de Java",
        "summary": {
            "page_count": 1,
            "element_count": 2,
            "observation_count": 0,
            "obligation_count": 0,
            "element_types": {"heading": 1, "paragraph": 1},
        },
    },
    "provenance": {
        "duration_ms": 1500,
        "provider_version": "1.32.0",
        "cache_key": "cache:sha256:abc123",
    },
}


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=ToolboxStructureClient)
    client.base_url = "http://localhost:8002"
    client.provider = "docling"
    return client


@pytest.fixture
def mock_artifact_client():
    return AsyncMock(spec=ToolboxArtifactClient)


def test_extract_returns_toolbox_extraction(mock_client, mock_artifact_client):
    """Verifica que extract() retorna um ToolboxExtraction com dados corretos."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
    mock_artifact_client.upload = AsyncMock(return_value="sha256:abc123")

    extractor = ToolboxManifestExtractor(
        client=mock_client,
        artifact_client=mock_artifact_client,
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


def test_extract_without_artifact_store_skips_upload(mock_client, mock_artifact_client):
    """Quando use_artifact_store=False, não chama upload."""
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)

    extractor = ToolboxManifestExtractor(
        client=mock_client,
        artifact_client=mock_artifact_client,
        use_artifact_store=False,
    )
    result = extractor.extract(FIXTURE_PDF)

    mock_artifact_client.upload.assert_not_called()
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


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Dual mode persists the secondary extraction under settings.data_dir."""
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)


def test_dual_mode_attaches_page_evidence_without_replacing_manifest(
    mock_client, monkeypatch
):
    """Dual extraction supplies fusion evidence to the PDDL manifest builder."""
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
    secondary_response = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    secondary_response["document"]["elements"][1]["text"] += " Conteúdo divergente."
    secondary_client = AsyncMock(spec=ToolboxStructureClient)
    secondary_client.provider = "mineru"
    secondary_client.extract_structure.return_value = secondary_response

    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client",
        lambda client_cls, **kwargs: secondary_client,
    )
    result = ToolboxManifestExtractor(
        client=mock_client,
        use_artifact_store=False,
    ).extract(FIXTURE_PDF)

    assert result.document["document"] == SAMPLE_TOOLBOX_RESPONSE["document"]
    assert (
        result.document["fusion_evidence"]["pages"][0]["page_number"] == 1
    )
    assert (
        result.document["fusion_evidence"]["pages"][0]["stats"]["provider_count"]
        == 2
    )
    assert result.document["fusion_evidence"]["pages"][0]["stats"]["text_divergence"]
    mock_client.extract_structure.assert_awaited_once()
    secondary_client.extract_structure.assert_awaited_once()
    secondary_client.close.assert_awaited_once()

    from backend.core.manifest.builder import build_processing_manifest
    from backend.core.planning.domain_bundle import DomainBundle
    from backend.core.planning.pddl_processor import PddlProblemCompiler

    manifest = build_processing_manifest(FIXTURE_PDF, deepcopy(result))
    assert any(item.kind == "fuse-providers" for item in manifest.obligations)
    compiled = PddlProblemCompiler(DomainBundle.load()).compile(manifest)
    assert "fuse-providers" in compiled.text
    assert "dual-provider-fusion" in compiled.text

    # The secondary extraction is kept for the methods that choose between
    # providers, under a content-addressed name whose hash is recorded.
    import hashlib
    import json

    [artifact] = [a for a in manifest.artifacts if a.kind == "provider-extraction"]
    stored = Path(artifact.path).read_bytes()
    assert hashlib.sha256(stored).hexdigest() == artifact.sha256
    assert json.loads(stored) == {"provider": "mineru", "document": secondary_response}


def test_dual_mode_passes_configured_fusion_policy(mock_client, monkeypatch):
    from docstruct.policy import FusionPolicy

    from backend.config.settings import settings

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
    secondary_client = AsyncMock(spec=ToolboxStructureClient)
    secondary_client.provider = "mineru"
    secondary_client.extract_structure.return_value = deepcopy(
        SAMPLE_TOOLBOX_RESPONSE
    )
    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client",
        lambda client_cls, **kwargs: secondary_client,
    )
    seen: dict = {}

    def fake_fuse(*args, **kwargs):
        seen["policy"] = kwargs.get("policy")
        return {"fusion_stats": {}, "fusion_evidence": {"pages": []}}

    monkeypatch.setattr(
        "backend.pipeline.fusion.fuse_extraction_payloads", fake_fuse
    )
    policy = FusionPolicy(text_pick="mineru")

    ToolboxManifestExtractor(
        client=mock_client,
        use_artifact_store=False,
        fusion_policy=policy,
    ).extract(FIXTURE_PDF)

    assert seen["policy"] is policy


def test_matching_dual_providers_do_not_create_fusion_obligations(
    mock_client, monkeypatch
):
    from backend.config.settings import settings
    from backend.core.manifest.builder import build_processing_manifest

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
    secondary_client = AsyncMock(spec=ToolboxStructureClient)
    secondary_client.provider = "mineru"
    secondary_client.extract_structure.return_value = deepcopy(
        SAMPLE_TOOLBOX_RESPONSE
    )
    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client",
        lambda client_cls, **kwargs: secondary_client,
    )

    result = ToolboxManifestExtractor(
        client=mock_client,
        use_artifact_store=False,
    ).extract(FIXTURE_PDF)
    manifest = build_processing_manifest(FIXTURE_PDF, deepcopy(result))

    assert not result.document["fusion_evidence"]["pages"][0]["stats"][
        "provider_divergence"
    ]
    assert not any(
        item.kind in {"fuse-providers", "adjudicate-page"}
        for item in manifest.obligations
    )


def test_dual_mode_does_not_emit_evidence_when_secondary_provider_fails(
    mock_client, monkeypatch
):
    from backend.config.settings import settings
    from backend.tools.toolbox_client import ToolboxProviderUnavailable

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
    secondary_client = AsyncMock(spec=ToolboxStructureClient)
    secondary_client.extract_structure.side_effect = ToolboxProviderUnavailable(
        "provider indisponível"
    )
    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client",
        lambda client_cls, **kwargs: secondary_client,
    )

    result = ToolboxManifestExtractor(
        client=mock_client,
        use_artifact_store=False,
    ).extract(FIXTURE_PDF)

    assert "fusion_evidence" not in result.document
    assert "fusion_stats" not in result.document
    secondary_client.close.assert_awaited_once()

def test_secondary_extraction_write_failure_does_not_fail_extraction(
    tmp_path, monkeypatch
):
    """The artifact only feeds the provider-choice methods, which fail without it."""
    from backend.config.settings import settings
    from backend.core.manifest.toolbox_extractor import _persist_secondary_extraction

    blocker = tmp_path / "artifacts"
    blocker.write_text("not a directory")
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    assert _persist_secondary_extraction({"elements": []}, "mineru") == {}


def test_extract_builds_and_closes_its_own_clients(monkeypatch):
    """Without injected clients, each extraction builds fresh ones and closes them.

    extract() runs every document on a new event loop, so an HTTP connection
    must not be kept between calls.
    """
    built: list = []

    def factory(client_cls, **kwargs):
        client = AsyncMock(spec=client_cls)
        client.base_url = "http://localhost:8002"
        client.provider = "docling"
        client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
        client.upload = AsyncMock(return_value="sha256:abc123")
        built.append((client_cls, client))
        return client

    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client", factory
    )
    extractor = ToolboxManifestExtractor(use_artifact_store=True)

    extractor.extract(FIXTURE_PDF)
    extractor.extract(FIXTURE_PDF)

    assert [cls for cls, _ in built] == [
        ToolboxStructureClient, ToolboxArtifactClient,
        ToolboxStructureClient, ToolboxArtifactClient,
    ]
    for _, client in built:
        client.close.assert_awaited_once()
