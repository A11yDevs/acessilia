"""Testes de regressão para a seleção de engine e orquestrador em backend/service.py.

Cobre:
- _normalized_engine(): mapeamento de valores de PIPELINE_ENGINE
- _build_orchestrator(): tipo correto de orquestrador por engine
- Settings PDDL: defaults e aliases PMV_* retroativos
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
    svc = _reimport_service(monkeypatch, "legacy")
    assert svc._normalized_engine() == "legacy"


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
    svc = _reimport_service(monkeypatch, "unknown-engine")
    assert svc._normalized_engine() == "legacy"


# ---------------------------------------------------------------------------
# _build_orchestrator
# ---------------------------------------------------------------------------


def test_build_orchestrator_returns_legacy_by_default(monkeypatch):
    from backend.agents.orchestrator import AccessibilityOrchestrator

    svc = _reimport_service(monkeypatch, "legacy")
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, AccessibilityOrchestrator)


def test_build_orchestrator_returns_pddl_when_configured(monkeypatch):
    from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator

    monkeypatch.setattr(settings, "pddl_fast_downward", "")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "")
    svc = _reimport_service(monkeypatch, "pddl")
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, PddlAccessibilityOrchestrator)


def test_build_orchestrator_pddl_with_docling_enables_ocr(monkeypatch):
    from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
    from core.manifest.docling_extractor import DoclingManifestExtractor

    monkeypatch.setattr(settings, "structurer", "docling")
    monkeypatch.setattr(settings, "pddl_fast_downward", "")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "")
    svc = _reimport_service(monkeypatch, "pddl")
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, PddlAccessibilityOrchestrator)
    extractor = orchestrator.information_structural.extractor
    assert isinstance(extractor, DoclingManifestExtractor)
    assert extractor.enable_ocr is True


def test_build_orchestrator_pddl_without_docling_disables_ocr(monkeypatch):
    from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
    from core.manifest.docling_extractor import DoclingManifestExtractor

    monkeypatch.setattr(settings, "structurer", "pymupdf")
    monkeypatch.setattr(settings, "pddl_fast_downward", "")
    monkeypatch.setattr(settings, "pddl_fast_downward_alias", "")
    svc = _reimport_service(monkeypatch, "pddl")
    orchestrator = svc._build_orchestrator()
    assert isinstance(orchestrator, PddlAccessibilityOrchestrator)
    extractor = orchestrator.information_structural.extractor
    assert isinstance(extractor, DoclingManifestExtractor)
    assert extractor.enable_ocr is False


# ---------------------------------------------------------------------------
# Settings PDDL — defaults e aliases PMV_*
# ---------------------------------------------------------------------------


def test_settings_pddl_defaults():
    import os

    # Garantir que as envvars não estão setadas no ambiente de teste
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

    assert fresh.pipeline_engine == "legacy"
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
