"""Regression tests for engine and orchestrator selection in backend/service.py.

Covers:
- _normalized_engine(): mapping of PIPELINE_ENGINE values
- _build_orchestrator(): the correct orchestrator type per engine
- PDDL settings: defaults and backward-compatible PMV_* aliases
"""
from __future__ import annotations

import importlib

import pytest

from backend.config.settings import settings


# ---------------------------------------------------------------------------
# _normalized_engine
# ---------------------------------------------------------------------------


def _reimport_service(monkeypatch, engine_value: str):
    """Re-importa backend.service com PIPELINE_ENGINE sobrescrito."""
    monkeypatch.setattr(settings, "pipeline_engine", engine_value)
    import backend.service as svc

    importlib.reload(svc)
    return svc


def test_normalized_engine_legacy(monkeypatch):
    monkeypatch.setattr(settings, "pipeline_engine", "legacy")
    from backend.service import _normalized_engine

    with pytest.raises(RuntimeError, match="desativado"):
        _normalized_engine()


def test_normalized_engine_pddl(monkeypatch):
    svc = _reimport_service(monkeypatch, "pddl")
    assert svc._normalized_engine() == "pddl"


def test_normalized_engine_pmv_alias(monkeypatch):
    """Alias 'pmv' deve resolver para 'pddl'."""
    svc = _reimport_service(monkeypatch, "pmv")
    assert svc._normalized_engine() == "pddl"


def test_normalized_engine_case_insensitive(monkeypatch):
    svc = _reimport_service(monkeypatch, "  PDDL  ")
    assert svc._normalized_engine() == "pddl"


def test_normalized_engine_unknown_defaults_to_legacy(monkeypatch):
    monkeypatch.setattr(settings, "pipeline_engine", "unknown-engine")
    from backend.service import _normalized_engine

    with pytest.raises(RuntimeError, match="desativado"):
        _normalized_engine()


# ---------------------------------------------------------------------------
# _build_orchestrator
# ---------------------------------------------------------------------------


def test_build_orchestrator_returns_legacy_by_default(monkeypatch):
    monkeypatch.setattr(settings, "pipeline_engine", "legacy")
    from backend.service import _build_orchestrator

    with pytest.raises(RuntimeError, match="desativado"):
        _build_orchestrator()


def test_build_orchestrator_returns_pddl_when_configured(monkeypatch):
    from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator

    monkeypatch.setattr(settings, "pddl_fast_downward", "")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "")
    svc = _reimport_service(monkeypatch, "pddl")
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, PddlAccessibilityOrchestrator)


def test_build_orchestrator_pddl_with_docling_enables_ocr(monkeypatch):
    from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
    from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor

    monkeypatch.setattr(settings, "structurer", "docling")
    monkeypatch.setattr(settings, "pddl_fast_downward", "")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "")
    svc = _reimport_service(monkeypatch, "pddl")
    monkeypatch.setattr(svc, "DOCLING_AVAILABLE", True)
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, PddlAccessibilityOrchestrator)
    extractor = orchestrator.information_structural.extractor
    assert isinstance(extractor, ToolboxManifestExtractor)
    assert orchestrator.extractor_backend == "toolbox"


def test_build_orchestrator_pddl_with_structurer_pymupdf_uses_pymupdf_extractor(monkeypatch):
    from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
    from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor

    monkeypatch.setattr(settings, "structurer", "pymupdf")
    monkeypatch.setattr(settings, "pddl_fast_downward", "")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "")
    svc = _reimport_service(monkeypatch, "pddl")
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, PddlAccessibilityOrchestrator)
    extractor = orchestrator.information_structural.extractor
    assert isinstance(extractor, ToolboxManifestExtractor)
    assert orchestrator.extractor_backend == "toolbox"


def test_build_orchestrator_pddl_without_docling_falls_back_to_pymupdf(monkeypatch):
    from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
    from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor

    monkeypatch.setattr(settings, "structurer", "docling")
    monkeypatch.setattr(settings, "pddl_fast_downward", "")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "")
    svc = _reimport_service(monkeypatch, "pddl")
    monkeypatch.setattr(svc, "DOCLING_AVAILABLE", False)
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, PddlAccessibilityOrchestrator)
    extractor = orchestrator.information_structural.extractor
    assert isinstance(extractor, ToolboxManifestExtractor)
    assert orchestrator.extractor_backend == "toolbox"


# ---------------------------------------------------------------------------
# Toolbox backend
# ---------------------------------------------------------------------------


def test_build_orchestrator_pddl_with_toolbox_uses_toolbox_extractor(monkeypatch):
    """STRUCTURER=toolbox + PIPELINE_ENGINE=pddl seleciona ToolboxManifestExtractor."""
    from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
    from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor

    monkeypatch.setattr(settings, "structurer", "toolbox")
    monkeypatch.setattr(settings, "pddl_fast_downward", "")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "")
    svc = _reimport_service(monkeypatch, "pddl")
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, PddlAccessibilityOrchestrator)
    extractor = orchestrator.information_structural.extractor
    assert isinstance(extractor, ToolboxManifestExtractor)
    assert orchestrator.extractor_backend == "toolbox"


def test_resolved_structurer_toolbox_does_not_require_docling(monkeypatch):
    """STRUCTURER=toolbox não depende de DOCLING_AVAILABLE."""
    monkeypatch.setattr(settings, "structurer", "toolbox")
    monkeypatch.setattr(settings, "pipeline_engine", "pddl")
    from backend.service import _resolved_structurer

    assert _resolved_structurer() == "toolbox"


def test_resolved_structurer_toolbox_without_docling(monkeypatch):
    """STRUCTURER=toolbox funciona mesmo quando docling não está instalado."""
    monkeypatch.setattr(settings, "structurer", "toolbox")
    monkeypatch.setattr(settings, "pipeline_engine", "pddl")
    monkeypatch.setattr("backend.service.DOCLING_AVAILABLE", False)
    from backend.service import _resolved_structurer

    assert _resolved_structurer() == "toolbox"


def test_toolbox_settings_defaults():
    """Settings da Toolbox carregam defaults corretos."""
    import os

    for key in (
        "TOOLBOX_BASE_URL",
        "TOOLBOX_PROVIDER",
        "TOOLBOX_TIMEOUT_SECONDS",
        "TOOLBOX_USE_ARTIFACT_STORE",
        "TOOLBOX_USE_REMOTE_CACHE",
    ):
        os.environ.pop(key, None)

    import backend.config.settings as cfg_mod

    fresh = cfg_mod.Settings()

    assert fresh.toolbox_base_url == "http://localhost:8002"
    assert fresh.toolbox_provider == "docling"
    assert fresh.toolbox_timeout_seconds == 3600
    assert fresh.toolbox_use_artifact_store is True
    assert fresh.toolbox_use_remote_cache is True


# ---------------------------------------------------------------------------
# Settings PDDL — defaults e aliases PMV_*
# ---------------------------------------------------------------------------


def test_settings_pddl_defaults():
    import os

    # Ensure the env vars are not set in the test environment.
    for key in (
        "PIPELINE_ENGINE",
        "PDDL_EXECUTE_DRY_RUN",
        "PMV_EXECUTE_DRY_RUN",
        "PDDL_PLANNER_BACKEND",
        "PDDL_PREFERRED_PLAN",
        "PDDL_FAST_DOWNWARD",
        "PDDL_FAST_DOWNWARD_ALIAS",
        "PDDL_FAST_DOWNWARD_SEARCH",
    ):
        os.environ.pop(key, None)

    from dataclasses import fields
    import backend.config.settings as cfg_mod

    fresh = cfg_mod.Settings()

    assert fresh.pipeline_engine == "pddl"
    assert fresh.pddl_execute_dry_run is True
    assert fresh.pddl_planner_backend == "internal"
    assert fresh.pddl_preferred_plan == "internal"
    assert fresh.pddl_fast_downward == ""
    assert fresh.pddl_fast_downward_alias == ""
    assert fresh.pddl_fast_downward_search == "astar(blind())"


def test_settings_pmv_aliases_reflect_pddl_values(monkeypatch):
    monkeypatch.setattr(settings, "pddl_execute_dry_run", False)
    monkeypatch.setattr(settings, "pddl_planner_backend", "fast-downward")
    monkeypatch.setattr(settings, "pddl_preferred_plan", "fast-downward")
    monkeypatch.setattr(settings, "pddl_fast_downward", "/usr/bin/downward")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "lama-first")
    monkeypatch.setattr(settings, "pddl_fast_downward_search", "custom()")

    assert settings.pmv_execute_dry_run is False
    assert settings.pmv_planner_backend == "fast-downward"
    assert settings.pmv_preferred_plan == "fast-downward"
    assert settings.pmv_fast_downward == "/usr/bin/downward"
    assert settings.pmv_fast_downward_alias == "lama-first"
    assert settings.pmv_fast_downward_search == "custom()"


def test_settings_api_defaults():
    """Campos de API introduzidos pela branch api-standalone devem ter defaults corretos."""
    import os

    for key in ("API_HOST", "API_PORT", "API_BASE_URL", "WEB_PORT"):
        os.environ.pop(key, None)

    import backend.config.settings as cfg_mod

    fresh = cfg_mod.Settings()
    assert fresh.api_host == "0.0.0.0"
    assert fresh.api_port == 8000
    assert fresh.api_base_url == "http://localhost:8000"
    assert fresh.web_port == 8001
    assert "api" in fresh.enabled_interfaces
