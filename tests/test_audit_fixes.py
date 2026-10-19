import sqlite3
import httpx
import pytest
from backend.api import worker
from backend.api.routes import jobs
from backend.config.settings import settings
from backend.services import job_store
from tests.test_pending_fixes import isolated_runtime as runtime_fixture

isolated_runtime = runtime_fixture


@pytest.mark.asyncio
async def test_position_persistence_failure_preserves_accepted_receipt(
    isolated_runtime, monkeypatch
):
    from backend.api.app import create_app

    queue, _ = isolated_runtime

    def fail(*args):
        raise sqlite3.OperationalError("synthetic locked database")

    monkeypatch.setattr(jobs, "save_status", fail)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/jobs",
            files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 202
    assert queue.qsize() == 1
    task_id = next(iter(worker.queued_jobs))
    assert job_store.load_record(task_id) is not None
    assert list((settings.temp_dir / "uploads").iterdir())
    assert response.json()["job_token"]
    assert response.json()["task_id"] == task_id


@pytest.mark.parametrize(
    "metadata", [{"column_index": 100000}, {"column_index": -1}, {"column_index": True}]
)
def test_core_rejects_unbounded_header_columns(metadata):
    from docstruct.tables.ast import _effective_headers

    with pytest.raises(ValueError, match="column index"):
        _effective_headers([{"cells": [{"text": "H", "metadata": metadata}]}])


@pytest.mark.asyncio
async def test_shutdown_while_sending_email_preserves_completed_download(
    isolated_runtime, monkeypatch, tmp_path
):
    import asyncio

    _, manager = isolated_runtime
    source = tmp_path / "completed.pdf"
    source.write_bytes(b"%PDF")
    job_store.save_request("finished", "token", {}, {"status": "queued"})

    async def process(*a, **k):
        return {"title": "Example", "sections": []}

    def export(doc, destination, *a, **k):
        destination.write_text("output")

    async def audio(text, destination, **k):
        destination.write_bytes(b"audio")

    async def confirmation(*a):
        return False

    started = asyncio.Event()

    async def email(*a, **k):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("backend.service.process", process)
    for name in [
        "export_txt",
        "export_docx",
        "export_pdf",
        "export_pdf_ua",
        "export_drbench_md",
        "export_accessible_document",
    ]:
        monkeypatch.setattr(worker, name, export)
    monkeypatch.setattr(worker, "export_mp3", audio)
    monkeypatch.setattr(worker, "send_confirmation_email", confirmation)
    monkeypatch.setattr(worker, "send_result_email", email)
    executor = worker.JobExecutor()
    task = asyncio.create_task(
        executor.run(
            worker.ApiJob(
                "finished", source, "completed.pdf", email="test@example.invalid"
            )
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 3)
        assert manager.obter("finished")["status"] == "done"
        out = settings.data_dir / "output/finished/completed_acessivel.zip"
        assert out.is_file()
        task.cancel()
        await task
        assert manager.obter("finished")["status"] == "done"
        assert manager.obter("finished")["email_delivery"] == "unknown"
        assert out.is_file()
        assert job_store.load_record("finished")["status"]["status"] == "done"

    finally:
        if not task.done():
            task.cancel()
        executor._executor.shutdown(wait=True)
