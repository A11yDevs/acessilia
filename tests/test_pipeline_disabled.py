"""Tests to verify legacy and local pipelines are disabled.

Ensures that only the PDDL+Toolbox pipeline can be used.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
from backend.service import _normalized_engine, _build_orchestrator


# ---------------------------------------------------------------------------
# Legacy pipeline must be disabled
# ---------------------------------------------------------------------------


class TestLegacyPipelineDisabled:
    def test_normalized_engine_raises_on_legacy(self):
        """_normalized_engine() must raise RuntimeError for legacy engine."""
        with patch("backend.service.settings.pipeline_engine", "legacy"):
            with pytest.raises(RuntimeError, match="desativado"):
                _normalized_engine()

    def test_normalized_engine_raises_on_unknown(self):
        """_normalized_engine() must raise RuntimeError for unknown engine."""
        with patch("backend.service.settings.pipeline_engine", "unknown"):
            with pytest.raises(RuntimeError, match="desativado"):
                _normalized_engine()

    def test_normalized_engine_accepts_pddl(self):
        """_normalized_engine() must return 'pddl' for pddl engine."""
        with patch("backend.service.settings.pipeline_engine", "pddl"):
            assert _normalized_engine() == "pddl"

    def test_normalized_engine_accepts_pmv(self):
        """_normalized_engine() must return 'pddl' for pmv alias."""
        with patch("backend.service.settings.pipeline_engine", "pmv"):
            assert _normalized_engine() == "pddl"

    def test_build_orchestrator_raises_on_legacy(self):
        """_build_orchestrator() must raise RuntimeError for legacy engine."""
        with patch("backend.service.settings.pipeline_engine", "legacy"):
            with pytest.raises(RuntimeError, match="desativado"):
                _build_orchestrator()

    def test_build_orchestrator_returns_pddl_toolbox(self):
        """_build_orchestrator() must return PddlAccessibilityOrchestrator with toolbox."""
        with patch("backend.service.settings.pipeline_engine", "pddl"):
            orchestrator = _build_orchestrator()
            assert isinstance(orchestrator, PddlAccessibilityOrchestrator)
            assert orchestrator.extractor_backend == "toolbox"


# ---------------------------------------------------------------------------
# Local extractors must be disabled in PddlAccessibilityOrchestrator
# ---------------------------------------------------------------------------


class TestLocalExtractorsDisabled:
    def test_pymupdf_extractor_raises(self):
        """PyMuPDF extractor must raise ValueError."""
        with pytest.raises(ValueError, match="desativado"):
            PddlAccessibilityOrchestrator(
                extractor_backend="pymupdf",
                execute_dry_run=True,
            )

    def test_docling_extractor_raises(self):
        """Docling extractor must raise ValueError."""
        with pytest.raises(ValueError, match="desativado"):
            PddlAccessibilityOrchestrator(
                extractor_backend="docling",
                execute_dry_run=True,
            )

    def test_docling_serve_extractor_raises(self):
        """Docling-serve extractor must raise ValueError."""
        with pytest.raises(ValueError, match="desativado"):
            PddlAccessibilityOrchestrator(
                extractor_backend="docling-serve",
                execute_dry_run=True,
            )

    def test_toolbox_extractor_works(self):
        """Toolbox extractor must work."""
        orchestrator = PddlAccessibilityOrchestrator(
            extractor_backend="toolbox",
            execute_dry_run=True,
        )
        assert orchestrator.extractor_backend == "toolbox"

    def test_toolbox_layout_extractor_works(self):
        """Toolbox-layout extractor must work (mapped to toolbox)."""
        orchestrator = PddlAccessibilityOrchestrator(
            extractor_backend="toolbox-layout",
            execute_dry_run=True,
        )
        assert orchestrator.extractor_backend == "toolbox-layout"


# ---------------------------------------------------------------------------
# Settings default must be pddl
# ---------------------------------------------------------------------------


class TestSettingsDefault:
    def test_pipeline_engine_default_is_pddl(self):
        """PIPELINE_ENGINE default must be 'pddl'."""
        # Unset the env var to test the default
        with patch.dict(os.environ, {}, clear=True):
            from backend.config.settings import settings
            assert settings.pipeline_engine == "pddl"

    def test_pipeline_engine_accepts_pddl_env(self):
        """PIPELINE_ENGINE=pddl must be accepted."""
        with patch.dict(os.environ, {"PIPELINE_ENGINE": "pddl"}, clear=True):
            from backend.config.settings import settings
            assert settings.pipeline_engine == "pddl"