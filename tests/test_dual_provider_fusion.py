"""Tests for the dual-provider-fusion PDDL method handler."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path

import pytest

from backend.agents.pddl_orchestrator import (
    _handle_dual_provider_fusion_method,
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
        "document": {"elements": []},
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

