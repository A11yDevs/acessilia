"""Testes para o ToolboxManifestExtractor.

Valida que a extração remota via Toolbox produz um ProcessingManifest válido
compatível com o pipeline PDDL.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, Mock

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


@pytest.mark.parametrize("apply_routes", [True, False])
def test_dual_mode_takes_the_page_the_router_sends_to_mineru(
    mock_client, monkeypatch, apply_routes
):
    """MinerU's page replaces docling's where the deterministic router prefers it."""
    import json

    from backend.config.settings import settings

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    monkeypatch.setattr(settings, "fusion_apply_page_routes", apply_routes)
    monkeypatch.setattr(
        "backend.pipeline.fusion.decide_v1",
        lambda primary, secondary: ("mineru", "both_formula->mineru"),
    )
    mock_client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
    secondary_response = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    secondary_response["document"]["elements"][1]["text"] = "MinerU transcription."
    secondary_client = AsyncMock(spec=ToolboxStructureClient)
    secondary_client.provider = "mineru"
    secondary_client.extract_structure.return_value = secondary_response
    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client",
        lambda client_cls, **kwargs: secondary_client,
    )

    result = ToolboxManifestExtractor(
        client=mock_client, use_artifact_store=False
    ).extract(FIXTURE_PDF)

    elements = result.document["document"]["elements"]
    stored = json.loads(Path(result.document["secondary_extraction"]["path"]).read_bytes())
    if apply_routes:
        assert [e["id"] for e in elements] == [
            "mineru-element-000001",
            "mineru-element-000002",
        ]
        assert elements[1]["text"] == "MinerU transcription."
        assert [e["id"] for e in stored["replaced_primary_pages"]["1"]] == [
            "element-000001",
            "element-000002",
        ]

        # The mixed document is still a valid manifest the planner can use, and
        # its elements say which provider they came from (the VLM judge reads it).
        from backend.core.manifest.builder import build_processing_manifest
        from backend.core.planning.domain_bundle import DomainBundle
        from backend.core.planning.pddl_processor import PddlProblemCompiler

        manifest = build_processing_manifest(FIXTURE_PDF, deepcopy(result))
        assert [e.id for e in manifest.elements] == [
            "mineru-element-000001",
            "mineru-element-000002",
        ]
        assert all(e.metadata["provider"] == "mineru" for e in manifest.elements)
        assert manifest.pages[0].element_ids == [e.id for e in manifest.elements]
        assert any(item.kind == "fuse-providers" for item in manifest.obligations)
        compiled = PddlProblemCompiler(DomainBundle.load()).compile(manifest)
        assert "fuse-providers" in compiled.text
    else:
        assert result.document["document"] == SAMPLE_TOOLBOX_RESPONSE["document"]
        assert "replaced_primary_pages" not in stored


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


def test_multi_endpoint_extraction_builds_no_artifact_upload_client(monkeypatch):
    from acessilia_sdk.toolbox import ToolboxEndpoint

    built = []

    def factory(client_cls, **kwargs):
        assert client_cls is ToolboxStructureClient
        client = AsyncMock(spec=client_cls)
        client.base_url = "http://toolbox-a.test"
        client.endpoints = (
            ToolboxEndpoint(client.base_url),
            ToolboxEndpoint("http://toolbox-b.test"),
        )
        client.provider = "docling"
        client.extract_structure.return_value = SAMPLE_TOOLBOX_RESPONSE
        built.append(client)
        return client

    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client", factory
    )
    result = ToolboxManifestExtractor(use_artifact_store=True).extract(
        FIXTURE_PDF, dual_fusion=False
    )
    assert len(built) == 1
    built[0].extract_structure.assert_awaited_once_with(
        file_path=FIXTURE_PDF.resolve(),
        artifact_id=None,
        language="pt-BR",
        use_remote_cache=True,
    )
    built[0].close.assert_awaited_once()
    assert result.configuration["use_artifact_store"] is False


@pytest.mark.parametrize("artifact_url", ["http://toolbox-a.test", "http://toolbox-b.test"])
def test_created_upload_client_must_share_the_structure_endpoint(
    mock_client, mock_artifact_client, monkeypatch, artifact_url
):
    from acessilia_sdk.toolbox import ToolboxEndpoint

    mock_client.endpoints = (ToolboxEndpoint("http://toolbox-a.test"),)
    mock_client.extract_structure.return_value = SAMPLE_TOOLBOX_RESPONSE
    mock_artifact_client.endpoints = (ToolboxEndpoint(artifact_url),)
    mock_artifact_client.upload.return_value = "sha256:stored"
    factory = Mock(return_value=mock_artifact_client)
    monkeypatch.setattr("backend.core.manifest.toolbox_extractor.make_toolbox_client", factory)

    result = ToolboxManifestExtractor(client=mock_client, use_artifact_store=True).extract(
        FIXTURE_PDF, dual_fusion=False
    )

    factory.assert_called_once_with(ToolboxArtifactClient)
    same_deployment = artifact_url == "http://toolbox-a.test"
    if same_deployment:
        mock_artifact_client.upload.assert_awaited_once_with(FIXTURE_PDF.resolve())
    else:
        mock_artifact_client.upload.assert_not_awaited()
    assert result.configuration["use_artifact_store"] is same_deployment
    assert result.artifact_id == ("sha256:stored" if same_deployment else None)
    mock_client.extract_structure.assert_awaited_once_with(
        file_path=None if same_deployment else FIXTURE_PDF.resolve(),
        artifact_id=result.artifact_id, language="pt-BR", use_remote_cache=True,
    )
    mock_artifact_client.close.assert_awaited_once()
    mock_client.close.assert_not_awaited()


def test_secondary_on_another_deployment_receives_source_not_primary_artifact(
    mock_client, mock_artifact_client, monkeypatch
):
    from acessilia_sdk.toolbox import ToolboxEndpoint
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    mock_client.endpoints = (ToolboxEndpoint("http://toolbox-a.test"),)
    mock_artifact_client.endpoints = mock_client.endpoints
    mock_artifact_client.upload.return_value = "sha256:primary"
    mock_client.extract_structure.return_value = SAMPLE_TOOLBOX_RESPONSE
    secondary = AsyncMock(spec=ToolboxStructureClient)
    secondary.provider = "mineru"
    secondary.endpoints = (ToolboxEndpoint("http://toolbox-b.test"),)
    secondary.extract_structure.return_value = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client",
        lambda client_cls, **kwargs: secondary,
    )
    result = ToolboxManifestExtractor(
        client=mock_client,
        artifact_client=mock_artifact_client,
        use_artifact_store=True,
    ).extract(FIXTURE_PDF)
    assert result.artifact_id == "sha256:primary"
    assert (
        mock_client.extract_structure.call_args.kwargs["artifact_id"]
        == "sha256:primary"
    )
    secondary.extract_structure.assert_awaited_once_with(
        file_path=FIXTURE_PDF.resolve(),
        artifact_id=None,
        language="pt-BR",
        use_remote_cache=True,
    )
    secondary.close.assert_awaited_once()


@pytest.mark.parametrize("failure_name", ["ToolboxTimeout", "ToolboxProviderUnavailable"])
def test_transient_upload_failure_uses_direct_extraction(
    mock_client, mock_artifact_client, failure_name
):
    from acessilia_sdk.toolbox import errors

    mock_artifact_client.upload.side_effect = getattr(errors, failure_name)("upload unavailable")
    mock_client.extract_structure.return_value = SAMPLE_TOOLBOX_RESPONSE
    result = ToolboxManifestExtractor(
        client=mock_client, artifact_client=mock_artifact_client, use_artifact_store=True,
    ).extract(FIXTURE_PDF, dual_fusion=False)
    mock_client.extract_structure.assert_awaited_once_with(
        file_path=FIXTURE_PDF.resolve(), artifact_id=None, language="pt-BR", use_remote_cache=True,
    )
    assert result.artifact_id is None
    assert result.configuration["use_artifact_store"] is False
    assert result.configuration["artifact_upload_error"] == failure_name


@pytest.mark.parametrize("failure_name", [
    "ToolboxAuthenticationError", "ToolboxInvalidInput", "ToolboxContractViolation",
])
def test_permanent_upload_failure_is_not_bypassed(mock_client, mock_artifact_client, failure_name):
    from acessilia_sdk.toolbox import errors

    failure = getattr(errors, failure_name)("permanent failure")
    mock_artifact_client.upload.side_effect = failure
    with pytest.raises(type(failure)):
        ToolboxManifestExtractor(
            client=mock_client, artifact_client=mock_artifact_client, use_artifact_store=True,
        ).extract(FIXTURE_PDF, dual_fusion=False)
    mock_client.extract_structure.assert_not_awaited()


@pytest.mark.parametrize("primary_ok,secondary_ok", [(True, True), (True, False), (False, True), (False, False)])
def test_dual_extraction_handles_each_provider_independently(
    mock_client, monkeypatch, primary_ok, secondary_ok
):
    from backend.config.settings import settings
    from acessilia_sdk.toolbox.errors import ToolboxProviderUnavailable, ToolboxUnavailable

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    primary = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    secondary_payload = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    secondary_payload["provider"] = "mineru"
    secondary_payload["provenance"]["cache_key"] = "secondary-key"
    secondary_payload["provenance"]["provider_version"] = "secondary-version"
    if primary_ok:
        mock_client.extract_structure.return_value = primary
    else:
        mock_client.extract_structure.side_effect = ToolboxProviderUnavailable("primary down")
    secondary = AsyncMock(spec=ToolboxStructureClient)
    secondary.provider = "mineru"
    secondary.base_url = "http://localhost:8002"
    if secondary_ok:
        secondary.extract_structure.return_value = secondary_payload
    else:
        secondary.extract_structure.side_effect = ToolboxProviderUnavailable("secondary down")
    monkeypatch.setattr("backend.core.manifest.toolbox_extractor.make_toolbox_client", lambda *a, **k: secondary)
    extractor = ToolboxManifestExtractor(client=mock_client, use_artifact_store=False)
    if not primary_ok and not secondary_ok:
        with pytest.raises(ToolboxUnavailable) as info:
            extractor.extract(FIXTURE_PDF)
        assert len(info.value.causes) == 2
    else:
        result = extractor.extract(FIXTURE_PDF)
        assert result.configuration["toolbox_provider"] == ("docling" if primary_ok else "mineru")
        if not primary_ok:
            assert result.cache_key == "secondary-key"
            assert result.version == "secondary-version"
        fusion = result.configuration["fusion"]
        if not (primary_ok and secondary_ok):
            assert result.configuration["extraction_degraded"] is True
            assert "fusion_evidence" not in result.document
            assert fusion["status"] == "degraded"
            assert fusion["providers"] == ["docling" if primary_ok else "mineru"]
            assert fusion["failed_providers"] == ["mineru" if primary_ok else "docling"]
        else:
            assert "fusion_evidence" in result.document
            assert fusion["status"] == "complete"
    mock_client.extract_structure.assert_awaited_once()
    secondary.extract_structure.assert_awaited_once()
    secondary.close.assert_awaited_once()


@pytest.mark.parametrize("failure_name", [
    "ToolboxUnsupportedMediaType", "ToolboxInvalidInput",
    "ToolboxAuthenticationError", "ToolboxContractViolation",
])
def test_dual_mode_preserves_permanent_primary_error(mock_client, monkeypatch, failure_name):
    from acessilia_sdk.toolbox import errors
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    failure = getattr(errors, failure_name)("permanent rejection")
    mock_client.extract_structure.side_effect = failure
    secondary = AsyncMock(spec=ToolboxStructureClient)
    secondary.extract_structure.side_effect = failure
    factory = lambda *a, **kw: secondary
    monkeypatch.setattr("backend.core.manifest.toolbox_extractor.make_toolbox_client", factory)
    with pytest.raises(type(failure)) as caught:
        ToolboxManifestExtractor(client=mock_client, use_artifact_store=False).extract(FIXTURE_PDF)
    assert caught.value is failure
    secondary.extract_structure.assert_not_awaited()


def test_dual_mode_preserves_permanent_secondary_error_without_primary(mock_client, monkeypatch):
    from acessilia_sdk.toolbox.errors import ToolboxTimeout, ToolboxUnsupportedMediaType
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    primary_error = ToolboxTimeout("primary unavailable")
    mock_client.extract_structure.side_effect = primary_error
    secondary = AsyncMock(spec=ToolboxStructureClient)
    secondary.provider = "mineru"
    secondary.extract_structure.side_effect = ToolboxUnsupportedMediaType("unsupported document")
    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client", lambda *a, **kw: secondary
    )
    with pytest.raises(ToolboxUnsupportedMediaType) as caught:
        ToolboxManifestExtractor(client=mock_client, use_artifact_store=False).extract(FIXTURE_PDF)
    assert caught.value.__cause__ is primary_error
    secondary.close.assert_awaited_once()


@pytest.mark.parametrize("failure_name", [
    "ToolboxUnsupportedMediaType", "ToolboxInvalidInput",
    "ToolboxAuthenticationError", "ToolboxContractViolation",
])
def test_permanent_secondary_error_keeps_the_primary_extraction(mock_client, monkeypatch, failure_name):
    from acessilia_sdk.toolbox import errors
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    mock_client.extract_structure.return_value = SAMPLE_TOOLBOX_RESPONSE
    secondary = AsyncMock(spec=ToolboxStructureClient)
    secondary.provider = "mineru"
    secondary.extract_structure.side_effect = getattr(errors, failure_name)("rejected")
    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client", lambda *a, **kw: secondary
    )
    result = ToolboxManifestExtractor(client=mock_client, use_artifact_store=False).extract(FIXTURE_PDF)
    assert result.configuration["toolbox_provider"] == "docling"
    assert result.configuration["extraction_degraded"] is True
    assert result.configuration["extraction_failures"] == {"mineru": failure_name}
    assert "fusion_evidence" not in result.document
    secondary.close.assert_awaited_once()


def test_dual_mode_falls_back_on_a_primary_http_500(mock_client, monkeypatch):
    import httpx
    from acessilia_sdk.toolbox.errors import ToolboxError
    from acessilia_sdk.toolbox.transport import raise_for_error
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    monkeypatch.setattr(settings, "fusion_secondary_provider", "mineru")
    with pytest.raises(ToolboxError) as server_error:
        raise_for_error(httpx.Response(500, json={"detail": "boom"}), "structure")
    mock_client.extract_structure.side_effect = server_error.value
    secondary_payload = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    secondary_payload["provider"] = "mineru"
    secondary = AsyncMock(spec=ToolboxStructureClient)
    secondary.provider = "mineru"
    secondary.base_url = "http://localhost:8002"
    secondary.extract_structure.return_value = secondary_payload
    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client", lambda *a, **kw: secondary
    )
    result = ToolboxManifestExtractor(client=mock_client, use_artifact_store=False).extract(FIXTURE_PDF)
    assert result.configuration["toolbox_provider"] == "mineru"
    assert result.configuration["extraction_failures"] == {"docling": "ToolboxError"}


def test_independent_endpoints_log_the_direct_input_policy_once(mock_client, mock_artifact_client, monkeypatch):
    from acessilia_sdk.toolbox import ToolboxEndpoint
    from backend.core.manifest import toolbox_extractor as module
    from backend.i18n import t
    from backend.log_messages import LOG_ARTIFACT_STORE_DIRECT_INPUT

    mock_client.endpoints = (
        ToolboxEndpoint("http://toolbox-a.test"), ToolboxEndpoint("http://toolbox-b.test"),
    )
    mock_artifact_client.endpoints = mock_client.endpoints
    mock_client.extract_structure.return_value = SAMPLE_TOOLBOX_RESPONSE
    info = Mock()
    monkeypatch.setattr(module.logger, "info", info)
    result = ToolboxManifestExtractor(
        client=mock_client, artifact_client=mock_artifact_client, use_artifact_store=True,
    ).extract(FIXTURE_PDF, dual_fusion=False)
    info.assert_called_once_with(t(LOG_ARTIFACT_STORE_DIRECT_INPUT))
    mock_artifact_client.upload.assert_not_awaited()
    assert result.artifact_id is None
    assert result.configuration["use_artifact_store"] is False
