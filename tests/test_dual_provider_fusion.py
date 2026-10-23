"""Tests for the dual-provider-fusion PDDL method handler."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path

import pytest

from backend.agents.pddl_orchestrator import (
    PddlAccessibilityOrchestrator,
    _handle_dual_provider_fusion_method,
    _handle_single_provider_method,
)
from backend.core.execution.executor import ExecutorAgent, MethodRegistry
from backend.core.manifest.models import (
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    ProcessingManifest,
    SourceDocument,
)
from backend.core.planning.planner_agent import PlannerAgent


def _make_manifest(tmp_path: Path, *, source_path: Path | None = None) -> ProcessingManifest:
    now = datetime(2026, 7, 28, tzinfo=timezone.utc)
    src = source_path or (tmp_path / "doc.pdf")
    return ProcessingManifest(
        manifest_id="manifest-fusion-test",
        created_at=now,
        source=SourceDocument(
            document_id="doc-fusion",
            filename=src.name,
            path=str(src),
            media_type="application/pdf",
            byte_size=1,
            sha256="a" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={"ocr": False},
        ),
        title="Documento de teste",
        language="pt-BR",
        pages=[],
        elements=[
            ManifestElement(
                id="element-1",
                type="paragraph",
                raw_label="paragraph",
                reading_order=1,
                hierarchy_level=0,
            )
        ],
        obligations=[
            Obligation(
                id="o-fuse",
                kind="fuse-providers",
                target_ids=["element-1"],
                admissible_methods=["dual-provider-fusion"],
                method_costs={"dual-provider-fusion": 12},
                rationale="Fundir dois providers",
            ),
        ],
        summary=ManifestSummary(
            page_count=0,
            element_count=1,
            observation_count=0,
            obligation_count=1,
            element_types={"paragraph": 1},
        ),
    )


def _dual_payload() -> dict:
    return {
        "status": "succeeded",
        "provider": "docling+mineru",
        "document": {"elements": [{"type": "paragraph", "text": "Recovered content"}]},
        "fusion_stats": {"pairs": 3, "matched": 25},
    }


def test_fusion_handler_returns_artifact_in_method_result(tmp_path, monkeypatch):
    manifest = _make_manifest(tmp_path)

    async def _fake_extract_fused(*args, **kwargs):
        return _dual_payload()

    monkeypatch.setattr(
        "backend.pipeline.fusion.extract_fused", _fake_extract_fused
    )
    result = _handle_dual_provider_fusion_method(manifest, "o-fuse")

    assert result.success is True
    assert result.validated is True
    # O handler NÃO deve modificar manifest.artifacts diretamente.
    assert manifest.artifacts == []
    # O artefato deve vir em MethodResult.artifacts.
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.kind == "fusion-payload"
    assert artifact.media_type == "application/json"
    # O payload deve ser realmente persistido em JSON.
    assert Path(artifact.path).exists()
    persisted = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
    assert persisted["provider"] == "docling+mineru"


def test_fusion_handler_fails_when_payload_not_succeeded(tmp_path, monkeypatch):
    manifest = _make_manifest(tmp_path)

    async def _fake_extract_fused(*args, **kwargs):
        return {"status": "failed", "document": {"elements": []}}

    monkeypatch.setattr(
        "backend.pipeline.fusion.extract_fused", _fake_extract_fused
    )
    result = _handle_dual_provider_fusion_method(manifest, "o-fuse")

    assert result.success is False
    assert result.validated is False
    assert result.artifacts == []
    assert manifest.artifacts == []


def test_fusion_handler_fails_on_unknown_obligation(tmp_path, monkeypatch):
    manifest = _make_manifest(tmp_path)

    async def _fake_extract_fused(*args, **kwargs):
        return _dual_payload()

    monkeypatch.setattr(
        "backend.pipeline.fusion.extract_fused", _fake_extract_fused
    )
    result = _handle_dual_provider_fusion_method(manifest, "o-inexistente")

    assert result.success is False
    assert result.validated is False
    assert result.artifacts == []


def test_fusion_handler_fails_when_single_provider(tmp_path, monkeypatch):
    """A ação planejada é dual-provider: um único provider deve falhar."""
    manifest = _make_manifest(tmp_path)

    async def _fake_extract_fused(*args, **kwargs):
        return {
            "status": "succeeded",
            "provider": "mineru",
            "document": {"elements": []},
        }

    monkeypatch.setattr(
        "backend.pipeline.fusion.extract_fused", _fake_extract_fused
    )
    result = _handle_dual_provider_fusion_method(manifest, "o-fuse")

    assert result.success is False
    assert result.validated is False
    assert "único provider" in (result.message or "")
    assert result.artifacts == []


def _forbid_toolbox(monkeypatch):
    """The single-provider fallback must reuse the manifest, never re-extract."""

    def fail(*_args, **_kwargs):
        raise AssertionError("single-provider called the Toolbox")

    monkeypatch.setattr("backend.tools.toolbox_client.make_toolbox_client", fail)


def test_single_provider_accepts_the_manifest_extraction_without_the_toolbox(
    tmp_path, monkeypatch
):
    manifest = _make_manifest(tmp_path)
    manifest.extractor.configuration["toolbox_provider"] = "docling"
    monkeypatch.setattr("backend.config.settings.settings.toolbox_provider", "docling")
    _forbid_toolbox(monkeypatch)

    result = _handle_single_provider_method(manifest, "o-fuse")

    assert result.success is True
    assert result.validated is True
    assert "docling" in (result.message or "")
    assert result.artifacts == []


@pytest.mark.parametrize(
    ("recorded", "expected_message"),
    [
        (None, "does not record"),
        ("mineru", "not by the configured provider"),
    ],
)
def test_single_provider_rejects_an_extraction_it_cannot_vouch_for(
    tmp_path, monkeypatch, recorded, expected_message
):
    manifest = _make_manifest(tmp_path)
    if recorded is not None:
        manifest.extractor.configuration["toolbox_provider"] = recorded
    monkeypatch.setattr("backend.config.settings.settings.toolbox_provider", "docling")
    _forbid_toolbox(monkeypatch)

    result = _handle_single_provider_method(manifest, "o-fuse")

    assert result.success is False
    assert result.validated is False
    assert expected_message in (result.message or "")


def test_pddl_replans_from_dual_to_single_provider(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    manifest = _make_manifest(tmp_path, source_path=source)
    obligation = manifest.obligations[0]
    obligation.admissible_methods.append("single-provider")
    obligation.method_costs["single-provider"] = 20
    monkeypatch.setattr("backend.config.settings.settings.data_dir", tmp_path)
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._run_extract_fused",
        lambda path, **_kwargs: {
            "status": "succeeded",
            "provider": "docling",
            "document": {"elements": []},
        },
    )
    manifest.extractor.configuration["toolbox_provider"] = "docling"
    monkeypatch.setattr("backend.config.settings.settings.toolbox_provider", "docling")
    executor = PddlAccessibilityOrchestrator._build_executor()

    _, first_plan = PlannerAgent().plan(manifest, selected_roots=["o-fuse"])
    after_first, first_report = executor.execute(
        first_plan, manifest, dry_run=False
    )

    assert first_report.replan_required is True
    assert [
        step.method for step in first_report.steps if step.method is not None
    ] == ["dual-provider-fusion"]

    _, fallback_plan = PlannerAgent().plan(
        after_first, selected_roots=["o-fuse"]
    )
    completed, fallback_report = executor.execute(
        fallback_plan, after_first, dry_run=False
    )

    assert fallback_report.status == "completed"
    assert [
        step.method for step in fallback_report.steps if step.method is not None
    ] == ["single-provider"]
    assert completed.obligations[0].status == "satisfied"


@pytest.mark.skipif(find_spec("agno") is None, reason="Agno não instalado")
def test_executor_wires_fusion_artifact_into_attempt(tmp_path, monkeypatch):
    """Proveniência: o ExecutorAgent associa o artefato à tentativa."""
    manifest = _make_manifest(tmp_path)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-fuse"])

    async def _fake_extract_fused(*args, **kwargs):
        return _dual_payload()

    monkeypatch.setattr(
        "backend.pipeline.fusion.extract_fused", _fake_extract_fused
    )

    registry = MethodRegistry()
    registry.register(
        "dual-provider-fusion", _handle_dual_provider_fusion_method
    )
    updated, report = ExecutorAgent(registry).execute(plan, manifest)

    assert report.status == "completed"
    fused = next(item for item in updated.obligations if item.id == "o-fuse")
    assert fused.status == "satisfied"
    assert len(fused.attempts) == 1
    attempt = fused.attempts[0]
    assert attempt.method == "dual-provider-fusion"
    assert len(attempt.artifact_ids) == 1
    artifact_id = attempt.artifact_ids[0]
    # O artefato deve existir no manifesto e estar associado à tentativa.
    assert any(a.id == artifact_id for a in updated.artifacts)
    artifact = next(a for a in updated.artifacts if a.id == artifact_id)
    assert artifact.kind == "fusion-payload"
    assert Path(artifact.path).exists()


@pytest.mark.parametrize(
    ("stored", "reused"),
    [
        # The extractor's artifact holds this very source (same digest).
        ("sha256:" + "a" * 64, "sha256:" + "a" * 64),
        # An id of another document, or not an artifact id, is not reused.
        ("sha256:" + "b" * 64, None),
        ("art-42", None),
    ],
)
def test_dual_fusion_reuses_the_extractor_artifact_of_this_source(
    tmp_path, monkeypatch, stored, reused
):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    manifest = _make_manifest(tmp_path, source_path=source)
    manifest.extractor.configuration["artifact_id"] = stored
    monkeypatch.setattr("backend.config.settings.settings.data_dir", tmp_path)
    seen: dict[str, object] = {}

    def fake_run(path, *, artifact_id=None):
        seen["artifact_id"] = artifact_id
        return {"status": "failed"}

    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._run_extract_fused", fake_run
    )

    _handle_dual_provider_fusion_method(manifest, "o-fuse")

    assert seen["artifact_id"] == reused
