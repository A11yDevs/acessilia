"""The model-call capacity is sized for the queue's concurrency (#590).

The runner rejects at capacity instead of queueing without bound (ADR-0021).
The queue's jobs multiply each stage's ``VISION_CONCURRENCY``, so the process
must reserve enough pending calls or over-capacity calls degrade objects as
if the provider had failed.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.config.settings import Settings, settings
from backend.services.queue_service import UnifiedQueue, unified_queue


def _isolated_dirs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))


def test_the_default_pending_capacity_covers_the_configured_jobs(monkeypatch, tmp_path):
    _isolated_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("QUEUE_MAX_CONCURRENT", "5")
    monkeypatch.setenv("VISION_CONCURRENCY", "2")
    monkeypatch.setenv("MODEL_CALL_WORKERS", "4")
    monkeypatch.delenv("MODEL_CALL_MAX_PENDING", raising=False)

    configured = Settings()

    # 5 jobs x 2 calls = 10, minus the 4 workers.
    assert configured.model_call_max_pending == 6
    assert configured.model_call_admission_floor() == 6
    assert configured.model_call_capacity_warning() is None


def test_an_explicit_pending_capacity_too_small_for_the_jobs_is_reported():
    configured = replace(
        settings,
        queue_max_concurrent=5,
        vision_concurrency=2,
        model_call_workers=4,
        model_call_max_pending=4,
    )

    warning = configured.model_call_capacity_warning()

    assert configured.model_call_admission_floor() == 6
    assert warning is not None
    assert "10 calls" in warning
    assert "Raise MODEL_CALL_MAX_PENDING to at least 6" in warning


def test_capacity_that_covers_the_jobs_is_not_reported():
    configured = replace(
        settings,
        queue_max_concurrent=5,
        vision_concurrency=2,
        model_call_workers=4,
        model_call_max_pending=6,
    )

    assert configured.model_call_capacity_warning() is None


def test_the_queue_uses_the_configured_concurrency():
    assert unified_queue.max_concurrent == settings.queue_max_concurrent


def test_the_queue_refuses_a_nonpositive_concurrency():
    with pytest.raises(ValueError):
        UnifiedQueue(max_concurrent=0)


def test_the_startup_warning_is_logged_once_per_process(monkeypatch):
    from acessilia_core import logger as core_logger
    from backend.config import process_setup

    warned: list[str] = []
    monkeypatch.setattr(process_setup, "_LOGGED_CONFIGURATION_WARNINGS", set())
    monkeypatch.setattr(core_logger, "logger", SimpleNamespace(warning=warned.append))
    configured = replace(
        settings,
        queue_max_concurrent=5,
        vision_concurrency=2,
        model_call_workers=4,
        model_call_max_pending=4,
    )

    process_setup.warn_model_call_capacity(configured)
    process_setup.warn_model_call_capacity(configured)

    assert len(warned) == 1
    assert "MODEL_CALL_MAX_PENDING" in warned[0]


def test_setup_process_runs_the_capacity_check(monkeypatch):
    from acessilia_core import i18n, logger as core_logger
    from backend.config import process_setup

    checked: list[object] = []
    monkeypatch.setattr(process_setup, "warn_model_call_capacity", checked.append)
    monkeypatch.setattr(process_setup, "warn_deprecated_configuration", lambda *a, **k: None)
    monkeypatch.setattr(core_logger, "setup_logger", lambda **_kwargs: None)
    monkeypatch.setattr(i18n, "configure_locales", lambda *_args: None)
    monkeypatch.setattr(i18n, "configure_server_locale", lambda *_args: None)

    process_setup.setup_process(settings, environ={})

    assert checked == [settings]
