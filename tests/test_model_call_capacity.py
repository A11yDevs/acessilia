"""The model-call capacity is sized for the queue's concurrency (#590).

The runner rejects at capacity instead of queueing without bound (ADR-0021).
The queue's jobs multiply each stage's ``VISION_CONCURRENCY``, so the process
must reserve enough pending calls or over-capacity calls degrade objects as
if the provider had failed. The same file covers the multi-job gate that keeps
that concurrency experimental until #238 W1 lands (#830).
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.config.settings import Settings, settings
from backend.services.model_calls import ModelCallExecutor, ModelCallLimits
from backend.services.queue_service import (
    QueueItem,
    UnifiedQueue,
    create_unified_queue,
    unified_queue,
)


async def _until(predicate, timeout: float = 10.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def _isolated_dirs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))


def test_the_default_pending_capacity_covers_the_configured_jobs(monkeypatch, tmp_path):
    _isolated_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("QUEUE_MAX_CONCURRENT", "5")
    monkeypatch.setenv("QUEUE_MULTI_JOB_EXPERIMENTAL", "true")
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
        queue_multi_job_experimental=True,
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
        queue_multi_job_experimental=True,
        vision_concurrency=2,
        model_call_workers=4,
        model_call_max_pending=6,
    )

    assert configured.model_call_capacity_warning() is None


def test_the_queue_uses_the_configured_concurrency():
    assert unified_queue.max_concurrent == settings.queue_max_concurrent


def test_multi_job_concurrency_requires_the_experimental_opt_in(monkeypatch, tmp_path):
    _isolated_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("QUEUE_MAX_CONCURRENT", "2")
    monkeypatch.delenv("QUEUE_MULTI_JOB_EXPERIMENTAL", raising=False)

    with pytest.raises(ValueError, match="QUEUE_MULTI_JOB_EXPERIMENTAL=true"):
        Settings()


@pytest.mark.parametrize("value", ["false", "0", "no", "off"])
def test_a_false_opt_in_does_not_enable_multi_job(monkeypatch, tmp_path, value):
    _isolated_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("QUEUE_MAX_CONCURRENT", "2")
    monkeypatch.setenv("QUEUE_MULTI_JOB_EXPERIMENTAL", value)

    with pytest.raises(ValueError, match="QUEUE_MULTI_JOB_EXPERIMENTAL=true"):
        Settings()


@pytest.mark.parametrize("value", ["", "maybe", "2"])
def test_unknown_opt_in_values_fail_closed(monkeypatch, tmp_path, value):
    _isolated_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("QUEUE_MAX_CONCURRENT", "2")
    monkeypatch.setenv("QUEUE_MULTI_JOB_EXPERIMENTAL", value)

    with pytest.raises(ValueError, match="QUEUE_MULTI_JOB_EXPERIMENTAL=true"):
        Settings()


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "sim", "TRUE", " true "])
def test_truthy_opt_in_values_enable_multi_job(monkeypatch, tmp_path, value):
    _isolated_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("QUEUE_MAX_CONCURRENT", "2")
    monkeypatch.setenv("QUEUE_MULTI_JOB_EXPERIMENTAL", value)

    configured = Settings()

    assert configured.queue_max_concurrent == 2
    assert configured.queue_multi_job_experimental is True


def test_single_job_concurrency_does_not_require_the_opt_in(monkeypatch, tmp_path):
    _isolated_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("QUEUE_MAX_CONCURRENT", "1")
    monkeypatch.delenv("QUEUE_MULTI_JOB_EXPERIMENTAL", raising=False)

    configured = Settings()

    assert configured.queue_max_concurrent == 1
    assert configured.queue_multi_job_experimental is False


def test_rebuilding_settings_revalidates_the_gate():
    with pytest.raises(ValueError, match="QUEUE_MULTI_JOB_EXPERIMENTAL=true"):
        replace(
            settings,
            queue_max_concurrent=2,
            queue_multi_job_experimental=False,
        )


def test_the_queue_constructor_requires_the_experimental_opt_in():
    with pytest.raises(ValueError, match="QUEUE_MULTI_JOB_EXPERIMENTAL=true"):
        UnifiedQueue(max_concurrent=2)

    queue = UnifiedQueue(max_concurrent=2, allow_multi_job=True)

    assert queue.max_concurrent == 2


def test_the_queue_factory_revalidates_a_mutated_settings():
    configured = replace(settings, queue_multi_job_experimental=False)
    configured.queue_max_concurrent = 2

    with pytest.raises(ValueError, match="QUEUE_MULTI_JOB_EXPERIMENTAL=true"):
        create_unified_queue(configured)


def test_the_queue_factory_accepts_a_mutated_settings_with_the_opt_in():
    configured = replace(settings, queue_multi_job_experimental=True)
    configured.queue_max_concurrent = 2

    assert create_unified_queue(configured).max_concurrent == 2


def test_a_queue_built_from_settings_uses_its_concurrency():
    configured = replace(
        settings, queue_max_concurrent=3, queue_multi_job_experimental=True
    )

    assert create_unified_queue(configured).max_concurrent == 3


def test_the_queue_refuses_a_nonpositive_concurrency():
    with pytest.raises(ValueError):
        UnifiedQueue(max_concurrent=0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("queue_max_concurrent", 0),
        ("model_call_workers", 0),
        ("vision_concurrency", 0),
        ("model_call_max_pending", -2),
    ],
)
def test_invalid_model_call_settings_are_refused(field, value):
    with pytest.raises(ValueError):
        replace(settings, **{field: value})


def test_the_minus_one_sentinel_derives_the_pending_floor():
    configured = replace(
        settings,
        queue_max_concurrent=5,
        queue_multi_job_experimental=True,
        vision_concurrency=2,
        model_call_workers=4,
        model_call_max_pending=-1,
    )

    # 5 jobs x 2 calls = 10, minus the 4 workers.
    assert configured.model_call_max_pending == 6


@pytest.mark.asyncio
async def test_queue_jobs_use_the_derived_model_call_capacity(tmp_path):
    """Two jobs at once share the process runner without an admission rejection.

    The deterministic integration: the queue starts both jobs, each submits
    two stage-bounded calls, and the runner has one worker plus the three
    pending slots derived from ``2 × 2 − 1``. The first provider call blocks,
    so the other three wait in the runner; once released, all complete.
    """
    configured = replace(
        settings,
        queue_max_concurrent=2,
        queue_multi_job_experimental=True,
        vision_concurrency=2,
        model_call_workers=1,
    )
    assert configured.model_call_admission_floor() == 3
    runner = ModelCallExecutor(
        ModelCallLimits(
            workers=configured.model_call_workers,
            max_pending=configured.model_call_admission_floor(),
        )
    )
    queue = create_unified_queue(configured)
    release = threading.Event()
    calls: list[str] = []
    lock = threading.Lock()

    def provider(label: str) -> str:
        with lock:
            calls.append(label)
        release.wait(10)
        return label

    async def job(label: str) -> list[str]:
        slots = asyncio.Semaphore(configured.vision_concurrency)

        async def one(index: int) -> str:
            async with slots:
                return await runner.run(
                    lambda: provider(f"{label}-{index}"),
                    timeout=10,
                    label=f"{label}-{index}",
                )

        return await asyncio.gather(*(one(index) for index in range(2)))

    results: dict[str, list[str]] = {}

    async def callback(label: str) -> None:
        results[label] = await job(label)

    queue.start_worker()
    try:
        for label in ("a", "b"):
            await queue.enqueue(
                QueueItem(
                    file_path=tmp_path / label,
                    filename=label,
                    source="test",
                    callback=callback,
                    callback_args={"label": label},
                )
            )
        await _until(lambda: runner.snapshot()["active"] == 1)
        await _until(lambda: runner.snapshot()["pending"] == 3)
        release.set()
        await _until(lambda: len(results) == 2)
    finally:
        release.set()
        if queue._worker_task is not None:
            queue._worker_task.cancel()
            await asyncio.gather(queue._worker_task, return_exceptions=True)
        runner.close(wait=True)

    assert results == {"a": ["a-0", "a-1"], "b": ["b-0", "b-1"]}
    assert sorted(calls) == ["a-0", "a-1", "b-0", "b-1"]


def test_the_startup_warning_is_logged_once_per_process(monkeypatch):
    from acessilia_core import logger as core_logger
    from backend.config import process_setup

    warned: list[str] = []
    monkeypatch.setattr(process_setup, "_LOGGED_CONFIGURATION_WARNINGS", set())
    monkeypatch.setattr(core_logger, "logger", SimpleNamespace(warning=warned.append))
    configured = replace(
        settings,
        queue_max_concurrent=5,
        queue_multi_job_experimental=True,
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

    checked: list[tuple[object, int | None]] = []
    monkeypatch.setattr(
        process_setup,
        "warn_model_call_capacity",
        lambda configured, *, jobs_at_once=None: checked.append((configured, jobs_at_once)),
    )
    monkeypatch.setattr(process_setup, "warn_deprecated_configuration", lambda *a, **k: None)
    monkeypatch.setattr(core_logger, "setup_logger", lambda **_kwargs: None)
    monkeypatch.setattr(i18n, "configure_locales", lambda *_args: None)
    monkeypatch.setattr(i18n, "configure_server_locale", lambda *_args: None)

    process_setup.setup_process(settings, environ={}, jobs_at_once=3)

    assert checked == [(settings, 3)]
