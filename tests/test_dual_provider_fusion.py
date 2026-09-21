"""Tests for the dual-provider-fusion PDDL method handler."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.agents.pddl_orchestrator import (
    _handle_dual_provider_fusion_method,
)
from backend.core.manifest.models import (
    Artifact,
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    ProcessingManifest,
    SourceDocument,
)


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


def test_fusion_handler_registers_artifact_on_success(tmp_path, monkeypatch):
    manifest = _make_manifest(tmp_path)

    async def _fake_extract_fused(*args, **kwargs):
        return {
            "status": "succeeded",
            "provider": "docling+mineru",
            "document": {"elements": []},
            "fusion_stats": {"pairs": 3},
        }

    monkeypatch.setattr(
        "backend.pipeline.fusion.extract_fused", _fake_extract_fused
    )
    result = _handle_dual_provider_fusion_method(manifest, "o-fuse")

    assert result.success is True
    assert result.validated is True
    assert any(
        artifact.kind == "fusion-payload"
        for artifact in manifest.artifacts
    )


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
    assert manifest.artifacts == []


def test_fusion_handler_fails_on_unknown_obligation(tmp_path, monkeypatch):
    manifest = _make_manifest(tmp_path)

    async def _fake_extract_fused(*args, **kwargs):
        return {"status": "succeeded", "document": {"elements": []}}

    monkeypatch.setattr(
        "backend.pipeline.fusion.extract_fused", _fake_extract_fused
    )
    result = _handle_dual_provider_fusion_method(manifest, "o-inexistente")

    assert result.success is False
    assert result.validated is False
