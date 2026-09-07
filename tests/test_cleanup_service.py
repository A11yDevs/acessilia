import asyncio
import os
import time

import pytest

from backend.config.settings import settings
from backend.services import cleanup_service
from backend.services.cleanup_service import _clean_output_directory


def _create_aged_output(output_dir, name, age_seconds):
    job_dir = output_dir / name
    job_dir.mkdir(parents=True)
    result = job_dir / "resultado.txt"
    result.write_text("resultado", encoding="utf-8")
    timestamp = time.time() - age_seconds
    os.utime(result, (timestamp, timestamp))
    os.utime(job_dir, (timestamp, timestamp))
    return job_dir


def test_output_cleanup_keeps_results_younger_than_seven_days(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    output_dir = tmp_path / "output"
    job_dir = _create_aged_output(output_dir, "job-recente", 25 * 60 * 60)

    _clean_output_directory()

    assert job_dir.exists()


def test_output_cleanup_removes_results_older_than_seven_days(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    output_dir = tmp_path / "output"
    job_dir = _create_aged_output(output_dir, "job-expirado", 8 * 24 * 60 * 60)

    _clean_output_directory()

    assert not job_dir.exists()


def test_periodic_cleanup_removes_expired_tokens(monkeypatch):
    calls = []

    async def remove_expired_tokens():
        calls.append(True)

    async def stop_after_first_cycle(_interval):
        raise asyncio.CancelledError

    monkeypatch.setattr(cleanup_service, "_clean_temp_directory", lambda: None)
    monkeypatch.setattr(cleanup_service, "_clean_output_directory", lambda: None)
    monkeypatch.setattr(cleanup_service, "limpar_tokens_expirados", remove_expired_tokens)
    monkeypatch.setattr(cleanup_service.asyncio, "sleep", stop_after_first_cycle)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cleanup_service.periodic_cleanup())

    assert calls == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["done", "error", "cancelled"])
async def test_temp_cleanup_preserves_queued_and_processing_uploads(
    monkeypatch, tmp_path, outcome
):
    from backend.services.queue_service import QueueItem, UnifiedQueue

    monkeypatch.setattr(settings, "temp_dir", tmp_path)
    queue = UnifiedQueue()
    monkeypatch.setattr(cleanup_service, "unified_queue", queue)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    pending = uploads / "pending.pdf"
    orphan = uploads / "orphan.pdf"
    recent = uploads / "recent.pdf"
    for path in (pending, orphan, recent):
        path.write_bytes(b"%PDF-1.4")
    old = time.time() - cleanup_service.FILE_MAX_AGE - 60
    for path in (pending, orphan, uploads):
        os.utime(path, (old, old))
    started = asyncio.Event()
    release = asyncio.Event()

    async def process():
        started.set()
        await release.wait()
        assert pending.read_bytes() == b"%PDF-1.4"
        if outcome == "error":
            raise RuntimeError("controlled failure")

    await queue.enqueue(QueueItem(
        file_path=pending, filename=pending.name, source="pytest",
        task_id="bug27", callback=process,
    ))
    cleanup_service._clean_temp_directory()
    assert pending.exists()
    assert queue.get_position("bug27") == 1
    assert not orphan.exists()
    assert recent.exists()

    queue.start_worker()
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert queue.get_position("bug27") == 0
        cleanup_service._clean_temp_directory()
        assert pending.exists()
        if outcome == "cancelled":
            queue._worker_task.cancel()
        else:
            release.set()
            await asyncio.sleep(0)
            assert queue.protected_file_paths() == set()
    finally:
        queue._worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queue._worker_task

    assert queue.protected_file_paths() == set()
    cleanup_service._clean_temp_directory()
    assert not pending.exists()
    assert recent.exists()


@pytest.mark.asyncio
async def test_temp_cleanup_removes_cancelled_queued_upload(monkeypatch, tmp_path):
    from backend.services.queue_service import QueueItem, UnifiedQueue

    monkeypatch.setattr(settings, "temp_dir", tmp_path)
    queue = UnifiedQueue()
    monkeypatch.setattr(cleanup_service, "unified_queue", queue)
    uploads = _create_aged_output(tmp_path, "uploads", cleanup_service.FILE_MAX_AGE + 60)
    pending = uploads / "resultado.txt"

    async def process():
        pytest.fail("Cancelled job must not run")

    await queue.enqueue(QueueItem(
        file_path=pending, filename=pending.name, source="pytest",
        task_id="cancel27", callback=process,
    ))
    cleanup_service._clean_temp_directory()
    assert pending.exists()
    assert queue.cancel("cancel27")
    cleanup_service._clean_temp_directory()
    assert not pending.exists()
    assert not uploads.exists()
