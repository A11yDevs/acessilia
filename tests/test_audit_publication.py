"""Atomic durable completion and shutdown after a real download publication."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from backend.api import worker
from backend.config.settings import settings
from backend.services import download_token_service, job_store, shutdown
from tests.test_pending_fixes import isolated_runtime as runtime_fixture

isolated_runtime = runtime_fixture


@pytest.fixture
def publication_job(isolated_runtime, monkeypatch, tmp_path):
    queue, manager = isolated_runtime
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-publication")
    task_id = "audit-publication"
    output = tmp_path / "output"
    job_store.save_request(
        task_id,
        "token",
        {
            "task_id": task_id,
            "file_path": str(path),
            "filename": "source.pdf",
            "output_dir": str(output),
        },
        {"task_id": task_id, "status": "queued"},
    )

    async def process(*_args, **kwargs):
        kwargs["outcome"].result_origin = "produced"
        return {"title": "Published document", "sections": []}

    def export(_document, destination, *_args, **_kwargs):
        destination.write_text("Published content", encoding="utf-8")

    async def audio(_text, destination, *_args, **_kwargs):
        destination.write_bytes(b"ID3-test")

    monkeypatch.setattr("backend.service.process", process)
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", False)
    monkeypatch.setattr(settings, "toolbox_docx_enabled", False)
    for name in ("export_txt", "export_accessible_document"):
        monkeypatch.setattr(worker, name, export)
    monkeypatch.setattr(worker, "export_mp3", audio)
    executor = worker.JobExecutor()
    yield (
        executor,
        worker.ApiJob(task_id, path, "source.pdf", output_dir=output),
        queue,
        manager,
    )
    executor._executor.shutdown(wait=True)
    shutdown.reset()


@pytest.mark.asyncio
async def test_shutdown_after_completed_attempt_preserves_published_job_and_no_recovery_replay(
    publication_job, monkeypatch
):
    executor, job, queue, manager = publication_job
    completed = asyncio.Event()
    release = asyncio.Event()
    original = executor._finish_attempt

    async def pause_after_completion(*args, **kwargs):
        await original(*args, **kwargs)
        if kwargs["state"] == "completed":
            completed.set()
            await release.wait()

    monkeypatch.setattr(executor, "_finish_attempt", pause_after_completion)
    task = asyncio.create_task(executor.run(job))
    try:
        await asyncio.wait_for(completed.wait(), 10)
        # At this exact boundary the audit result and terminal status already
        # share one durable commit, including the real token and output paths.
        status = job_store.load_record(job.task_id)["status"]
        assert status["status"] == "done"
        assert job_store.load_latest_attempt(job.task_id)["state"] == "completed"
        token = status["download_url"].rsplit("/", 1)[-1]
        info = await download_token_service.obter_info_token(token)
        assert info["task_id"] == job.task_id
        assert Path(info["output_dir"]).is_dir() and info["formats"]
        assert all(Path(item["file_path"]).is_file() for item in info["formats"])
        shutdown.begin_shutdown()
        task.cancel()
        await task
        assert manager.obter(job.task_id)["status"] == "done"
        assert job.output_dir.is_dir()
        assert job_store.load_record(job.task_id)["status"]["status"] == "done"
        shutdown.reset()
        manager._tasks.clear()
        manager._cancel_events.clear()
        await worker.recover_pending_jobs()
        assert queue.get_position(job.task_id) == 0
        assert job_store.load_latest_attempt(job.task_id)["state"] == "completed"
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_completed_status_and_attempt_are_one_sqlite_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_store.save_request("atomic", "token", {}, {"status": "processing"})
    job_store.save_attempt_start("atomic", {"id": "a"}, {"attempt": {"id": "a"}})
    connect = sqlite3.connect
    observed = []

    class Connection(sqlite3.Connection):
        def commit(self):
            if self.in_transaction:
                with connect(settings.db_path) as reader:
                    observed.append(
                        reader.execute(
                            "SELECT json_extract(j.status, '$.status'), a.state "
                            "FROM api_jobs j JOIN job_attempts a USING(task_id) WHERE j.task_id='atomic'"
                        ).fetchone()
                    )
            return super().commit()

    monkeypatch.setattr(
        job_store.sqlite3,
        "connect",
        lambda *a, **kw: connect(*a, **kw, factory=Connection),
    )
    job_store.save_attempt_result(
        "atomic",
        "a",
        state="completed",
        origin="produced",
        published_status={"status": "done", "download_url": "/download/existing-token"},
    )
    assert observed == [("processing", "started")]
    record, attempts = job_store.load_audit_view("atomic")
    assert record["status"]["status"] == "done" and attempts[0]["state"] == "completed"
    assert job_store.reconcile_started_attempts("atomic") == 0
    assert job_store.load_latest_attempt("atomic")["state"] == "completed"


def test_failed_completion_commit_rolls_back_both_records(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_store.save_request("atomic", "token", {}, {"status": "processing"})
    job_store.save_attempt_start("atomic", {"id": "a"}, {"attempt": {"id": "a"}})
    connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def commit(self):
            if self.in_transaction:
                raise sqlite3.OperationalError("injected completion commit failure")
            return super().commit()

    with monkeypatch.context() as patcher:
        patcher.setattr(
            job_store.sqlite3,
            "connect",
            lambda *a, **kw: connect(*a, **kw, factory=Connection),
        )
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            job_store.save_attempt_result(
                "atomic",
                "a",
                state="completed",
                origin="produced",
                published_status={"status": "done"},
            )
    record, attempts = job_store.load_audit_view("atomic")
    assert (
        record["status"]["status"] == "processing" and attempts[0]["state"] == "started"
    )


@pytest.mark.asyncio
async def test_audit_write_failure_cannot_prevent_completed_status(
    publication_job, monkeypatch
):
    executor, job, _, manager = publication_job

    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("injected audit failure")

    monkeypatch.setattr(worker, "save_attempt_result", fail)
    await executor.run(job)
    assert manager.obter(job.task_id)["status"] == "done"
    assert job_store.load_record(job.task_id)["status"]["status"] == "done"
    assert job.output_dir.is_dir()


@pytest.mark.asyncio
async def test_snapshot_failure_still_persists_completed_status(
    publication_job, monkeypatch
):
    executor, job, _, manager = publication_job

    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("injected snapshot failure")

    monkeypatch.setattr(worker, "save_attempt_start", fail)
    await executor.run(job)
    assert manager.obter(job.task_id)["status"] == "done"
    assert job_store.load_record(job.task_id)["status"]["status"] == "done"
    assert job_store.load_attempts(job.task_id) == []
    assert job.output_dir.is_dir()


@pytest.mark.asyncio
async def test_recovery_never_uses_completed_audit_alone_as_proof_of_publication(
    publication_job,
):
    _, job, queue, _ = publication_job
    job_store.save_attempt_start(
        job.task_id, {"id": "old-a"}, {"attempt": {"id": "old-a"}}
    )
    job_store.save_attempt_result(
        job.task_id, "old-a", state="completed", origin="produced"
    )
    job_store.save_status(job.task_id, {"task_id": job.task_id, "status": "processing"})
    # A record written by the earlier implementation can have completed audit
    # but no durable download/status evidence. Do not invent a delivered result.
    await worker.recover_pending_jobs()
    record = job_store.load_record(job.task_id)
    assert record["status"]["status"] == "error"
    assert not record["status"].get("download_url")
    assert queue.get_position(job.task_id) == 0
    assert job_store.load_latest_attempt(job.task_id)["state"] == "completed"
