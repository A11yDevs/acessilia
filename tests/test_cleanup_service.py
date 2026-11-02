import asyncio
import os
import time
import sqlite3

import pytest

from backend.config.settings import settings
from backend.services import cleanup_service
from backend.services.cleanup_service import _clean_output_directory
from backend.services import download_token_service as tokens


@pytest.fixture(autouse=True)
def isolate_token_connection(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(tokens, "_connection", None)
    yield
    if tokens._connection is not None:
        tokens._connection.close()
        tokens._connection = None


def _create_aged_output(output_dir, name, age_seconds):
    job_dir = output_dir / name
    job_dir.mkdir(parents=True)
    result = job_dir / "resultado.txt"
    result.write_text("resultado", encoding="utf-8")
    timestamp = time.time() - age_seconds
    os.utime(result, (timestamp, timestamp))
    os.utime(job_dir, (timestamp, timestamp))
    return job_dir


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["same", "alias", "child", "parent"])
async def test_temp_cleanup_preserves_active_download_tree(monkeypatch, tmp_path, reference):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    result_dir = _create_aged_output(settings.temp_dir, "custom", cleanup_service.FILE_MAX_AGE + 60)
    active = result_dir
    if reference == "alias":
        active = result_dir / ".." / "custom"
    elif reference == "child":
        active = _create_aged_output(result_dir, "nested", cleanup_service.FILE_MAX_AGE + 60)
    elif reference == "parent":
        active = settings.temp_dir
        (active / "resultado.txt").write_text("active")
    token = await tokens.criar_token(active, "resultado", formats=["txt"])
    cleanup_service._clean_temp_directory(set())
    info = await tokens.obter_info_token(token)
    assert info is not None and info["formats"][0]["ext"] == "txt"
    assert (active / "resultado.txt").is_file()


@pytest.mark.asyncio
async def test_temp_cleanup_only_protects_active_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    active = _create_aged_output(settings.temp_dir, "active", cleanup_service.FILE_MAX_AGE + 60)
    expired = _create_aged_output(settings.temp_dir, "expired", cleanup_service.FILE_MAX_AGE + 60)
    orphan = _create_aged_output(settings.temp_dir, "orphan", cleanup_service.FILE_MAX_AGE + 60)
    await tokens.criar_token(active, "resultado", formats=["txt"])
    token = await tokens.criar_token(expired, "resultado", formats=["txt"])
    connection = tokens._get_connection()
    connection.execute("UPDATE download_tokens SET criado_em=datetime('now', '-8 days') WHERE token=?", (token,))
    connection.commit()
    cleanup_service._clean_temp_directory(set())
    assert (active / "resultado.txt").is_file()
    assert not expired.exists()
    assert not orphan.exists()


def test_temp_cleanup_serializes_snapshot_with_token_creation(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    _create_aged_output(settings.temp_dir, "orphan", cleanup_service.FILE_MAX_AGE + 60)
    original = cleanup_service._is_stale
    checked = []

    def check_write_lock(path, now, max_age):
        with sqlite3.connect(settings.db_path, timeout=0) as independent:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                independent.execute("BEGIN IMMEDIATE")
        checked.append(path)
        return original(path, now, max_age)

    monkeypatch.setattr(cleanup_service, "_is_stale", check_write_lock)
    cleanup_service._clean_temp_directory(set())
    assert checked
    with sqlite3.connect(settings.db_path, timeout=0) as independent:
        independent.execute("BEGIN IMMEDIATE")  # released after the entire walk


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


def test_fusion_artifact_cleanup_uses_cache_retention(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    artifact_dir = tmp_path / "artifacts" / "fusion"
    artifact_dir.mkdir(parents=True)
    expired = artifact_dir / "inputs-expired.json"
    recent = artifact_dir / "secondary-recent.json"
    expired.write_text("expired", encoding="utf-8")
    recent.write_text("recent", encoding="utf-8")
    old_timestamp = time.time() - cleanup_service.CACHE_MAX_AGE - 60
    os.utime(expired, (old_timestamp, old_timestamp))

    cleanup_service._clean_fusion_artifact_directory()

    assert not expired.exists()
    assert recent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["same", "alias", "child", "parent"])
async def test_age_cleanup_preserves_valid_download_references(monkeypatch, tmp_path, reference):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_dir = _create_aged_output(tmp_path / "output", "old-result", 8 * 86400)
    active = job_dir
    if reference == "child":
        active = job_dir / "child"
        active.mkdir()
        (active / "resultado.txt").write_text("result", encoding="utf-8")
        old = time.time() - 8 * 86400
        for path in (active / "resultado.txt", active, job_dir):
            os.utime(path, (old, old))
    elif reference == "parent":
        active = job_dir.parent
        (active / "resultado.txt").write_text("result", encoding="utf-8")
    elif reference == "alias":
        active = job_dir / ".." / "old-result"
    token = await tokens.criar_token(active, "resultado", formats=["txt"])

    _clean_output_directory()

    assert job_dir.exists()
    assert await tokens.obter_info_token(token) is not None


@pytest.mark.asyncio
async def test_age_cleanup_removes_expired_unreferenced_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_dir = _create_aged_output(tmp_path / "output", "expired-result", 8 * 86400)
    token = await tokens.criar_token(job_dir, "resultado", formats=["txt"])
    connection = tokens._get_connection()
    connection.execute(
        "UPDATE download_tokens SET criado_em = datetime('now', '-8 days') WHERE token = ?",
        (token,),
    )
    connection.commit()

    _clean_output_directory()

    assert not job_dir.exists()


@pytest.mark.asyncio
async def test_cleanup_walk_does_not_block_event_loop(monkeypatch):
    import threading

    entered, release = threading.Event(), threading.Event()

    def slow_walk(*args):
        entered.set()
        assert release.wait(2)

    async def noop():
        return None

    monkeypatch.setattr(cleanup_service, "_clean_temp_directory", slow_walk)
    monkeypatch.setattr(cleanup_service, "_clean_output_directory", lambda: None)
    monkeypatch.setattr(cleanup_service, "_clean_in_memory_statuses", lambda: None)
    monkeypatch.setattr(cleanup_service, "limpar_tokens_expirados", noop)
    task = asyncio.create_task(cleanup_service.periodic_cleanup())
    try:
        for _ in range(100):
            await asyncio.sleep(0.005)
            if entered.is_set():
                break
        assert entered.is_set()
        assert not task.done()
    finally:
        release.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_periodic_cleanup_removes_expired_tokens(monkeypatch):
    calls = []

    async def remove_expired_tokens():
        calls.append(True)

    async def stop_after_first_cycle(_interval):
        raise asyncio.CancelledError

    monkeypatch.setattr(cleanup_service, "_clean_temp_directory", lambda *args: None)
    monkeypatch.setattr(cleanup_service, "_clean_output_directory", lambda: None)
    monkeypatch.setattr(cleanup_service, "limpar_tokens_expirados", remove_expired_tokens)
    monkeypatch.setattr(cleanup_service.asyncio, "sleep", stop_after_first_cycle)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cleanup_service.periodic_cleanup())

    assert calls == [True]


def test_cleanup_expires_terminal_statuses(monkeypatch, tmp_path):
    from backend.agents.state_manager import StateManager
    from backend.api import worker

    manager = StateManager()
    monkeypatch.setattr(cleanup_service, "state_manager", manager)
    monkeypatch.setattr(worker, "queued_jobs", {})

    finished = time.time() - cleanup_service.IN_MEMORY_STATUS_MAX_AGE - 60
    task_id = manager.criar_tarefa(tmp_path / "done.pdf")
    manager.atualizar(task_id, status="done")
    manager.obter(task_id)["fim"] = finished

    worker.register_queued_job("cancelledqueued", "queued.pdf", 1, "pytest")
    worker.queued_jobs["cancelledqueued"]["status"] = "cancelled"
    worker.queued_jobs["cancelledqueued"]["fim"] = finished

    cleanup_service._clean_in_memory_statuses()

    assert manager.obter(task_id) is None
    assert "cancelledqueued" not in worker.queued_jobs


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
    # Cancellation removes the file immediately, refreshing the directory mtime.
    assert not uploads.exists() or not any(uploads.iterdir())
