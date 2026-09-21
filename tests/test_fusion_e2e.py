"""End-to-end tests for the dual-provider fusion flow (Phase 5).

Two layers:

1. **Integration tests** (no network): mock ``extract_fused`` and validate the
   full handler → ExecutorAgent → provenance flow. These run in the normal
   gate.
2. **E2E tests** (``@pytest.mark.e2e``): require a running Acessilia Toolbox
   (``TOOLBOX_BASE_URL``) and a PDF fixture. They exercise the real
   ``extract_fused`` against both providers and validate the fused payload,
   the persisted artifact and the provenance chain.

Requires for the e2e layer:
- TOOLBOX_BASE_URL pointing to a running Toolbox with docling + mineru
- A PDF under 500KB under tests/fixtures/

E2E tests are excluded from CI via -m "not e2e".
"""
from __future__ import annotations

import json
import os
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


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path: Path, *, source_path: Path | None = None) -> ProcessingManifest:
    now = datetime(2026, 7, 28, tzinfo=timezone.utc)
    src = source_path or (tmp_path / "doc.pdf")
    return ProcessingManifest(
        manifest_id="manifest-fusion-e2e",
        created_at=now,
        source=SourceDocument(
            document_id="doc-fusion-e2e",
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


# ---------------------------------------------------------------------------
# Integration tests (no network — run in the normal gate)
# ---------------------------------------------------------------------------


def test_handler_returns_artifact_in_method_result(tmp_path, monkeypatch):
    manifest = _make_manifest(tmp_path)

    async def _fake_extract_fused(*args, **kwargs):
        return _dual_payload()

    monkeypatch.setattr(
        "backend.pipeline.fusion.extract_fused", _fake_extract_fused
    )
    result = _handle_dual_provider_fusion_method(manifest, "o-fuse")

    assert result.success is True
    assert result.validated is True
    assert manifest.artifacts == []
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.kind == "fusion-payload"
    assert artifact.media_type == "application/json"
    assert Path(artifact.path).exists()
    persisted = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
    assert persisted["provider"] == "docling+mineru"


def test_handler_fails_when_single_provider(tmp_path, monkeypatch):
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
    assert any(a.id == artifact_id for a in updated.artifacts)
    artifact = next(a for a in updated.artifacts if a.id == artifact_id)
    assert artifact.kind == "fusion-payload"
    assert Path(artifact.path).exists()


# ---------------------------------------------------------------------------
# E2E tests (require a running Toolbox)
# ---------------------------------------------------------------------------

TOOLBOX_BASE_URL = os.getenv("TOOLBOX_BASE_URL", "").strip()
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _get_small_pdf() -> Path:
    pdfs = sorted(FIXTURES_DIR.rglob("*.pdf"))
    if not pdfs:
        pytest.skip("No PDF fixtures found under tests/fixtures/")
    for pdf in pdfs:
        if pdf.stat().st_size < 500_000:
            return pdf
    return min(pdfs, key=lambda p: p.stat().st_size)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_extract_fused_against_real_toolbox():
    """Real dual-provider extraction via the Toolbox (docling + mineru)."""
    from backend.pipeline.fusion import extract_fused

    pdf = _get_small_pdf()
    payload = await extract_fused(pdf)

    assert payload.get("status") == "succeeded"
    provider = str(payload.get("provider") or "")
    assert "+" in provider, f"expected dual provider, got: {provider}"
    document = payload.get("document", {})
    elements = document.get("elements") or []
    assert len(elements) > 0, "fused payload must contain elements"
    assert "fusion_stats" in payload


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_fusion_handler_with_real_toolbox(tmp_path):
    """Full handler flow against the real Toolbox: payload → artifact."""
    pdf = _get_small_pdf()
    manifest = _make_manifest(tmp_path, source_path=pdf)

    result = _handle_dual_provider_fusion_method(manifest, "o-fuse")

    assert result.success is True, result.message
    assert result.validated is True
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.kind == "fusion-payload"
    assert artifact.media_type == "application/json"
    persisted = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
    assert "+" in str(persisted.get("provider") or "")
    assert len(persisted.get("document", {}).get("elements") or []) > 0


@pytest.mark.e2e
@pytest.mark.skipif(find_spec("agno") is None, reason="Agno não instalado")
def test_fusion_executor_e2e_with_real_toolbox(tmp_path):
    """Full PDDL → plan → execute flow against the real Toolbox."""
    pdf = _get_small_pdf()
    manifest = _make_manifest(tmp_path, source_path=pdf)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-fuse"])

    registry = MethodRegistry()
    registry.register(
        "dual-provider-fusion", _handle_dual_provider_fusion_method
    )
    updated, report = ExecutorAgent(registry).execute(plan, manifest)

    assert report.status == "completed", report.status
    fused = next(item for item in updated.obligations if item.id == "o-fuse")
    assert fused.status == "satisfied"
    assert len(fused.attempts) == 1
    attempt = fused.attempts[0]
    assert attempt.method == "dual-provider-fusion"
    assert attempt.status == "succeeded"
    assert len(attempt.artifact_ids) == 1
    artifact_id = attempt.artifact_ids[0]
    artifact = next(a for a in updated.artifacts if a.id == artifact_id)
    assert artifact.kind == "fusion-payload"
    persisted = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
    assert "+" in str(persisted.get("provider") or "")
