"""Cancellation, database responsiveness and private result recovery."""
import asyncio
import contextlib
import sqlite3
import threading

import httpx
import pytest

from backend.api import worker
from backend.api.routes import jobs
from backend.config.settings import settings
from backend.services import download_token_service, history_service, job_store, queue_service
from backend.services.queue_service import QueueItem, UnifiedQueue


@pytest.fixture
def isolated_runtime(monkeypatch, tmp_path):
    from backend import service
    from backend.agents.state_manager import StateManager
    from backend.api.limiter import limiter
    queue = UnifiedQueue()
    manager = StateManager()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(queue_service, "unified_queue", queue)
    monkeypatch.setattr(jobs, "unified_queue", queue)
    monkeypatch.setattr(worker, "queued_jobs", {})
    monkeypatch.setattr(worker, "state_manager", manager)
    monkeypatch.setattr(service, "state_manager", manager)
    monkeypatch.setattr(history_service, "_connection", None)
    monkeypatch.setattr(download_token_service, "_connection", None)
    monkeypatch.setattr(limiter, "enabled", False)
    yield queue, manager
    for module in (history_service, download_token_service):
        if module._connection is not None:
            module._connection.close()
            module._connection = None


async def stop_queue(queue):
    if queue._worker_task:
        queue._worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await queue._worker_task


@pytest.mark.asyncio
async def test_active_cancel_interrupts_pipeline_and_advances_queue(isolated_runtime, monkeypatch, tmp_path):
    from backend.api.app import create_app
    queue, manager = isolated_runtime
    started, advanced = asyncio.Event(), asyncio.Event()
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    executor = worker.JobExecutor()

    async def blocked_process(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    async def next_job():
        advanced.set()

    monkeypatch.setattr("backend.service.process", blocked_process)
    job_store.save_request("active", "capability", {}, {"task_id": "active", "status": "queued"})
    await queue.enqueue(QueueItem(source, "doc.pdf", "test", executor.run,
        {"job": worker.ApiJob("active", source, "doc.pdf")}, task_id="active"))
    await queue.enqueue(QueueItem(tmp_path / "next.pdf", "next.pdf", "test", next_job))
    queue.start_worker()
    try:
        await asyncio.wait_for(started.wait(), 2)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app()), base_url="http://test") as client:
            response = await client.post("/api/v1/jobs/active/cancel", headers={"X-Job-Token": "capability"})
        assert response.status_code == 200
        assert response.json()["status"] in {"cancelling", "cancelled"}
        await asyncio.wait_for(advanced.wait(), 2)
        async with asyncio.timeout(2):
            while "active" in queue._active_tasks:
                await asyncio.sleep(0.01)
        assert manager.obter("active")["status"] == "cancelled"
        assert job_store.load_record("active")["status"]["status"] == "cancelled"
        assert not source.exists()
        assert not queue._active_tasks.get("active")
    finally:
        await stop_queue(queue)
        executor._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_thread_operation_finishes_before_cancel_cleanup(isolated_runtime, tmp_path):
    queue, manager = isolated_runtime
    entered, release = threading.Event(), threading.Event()
    advanced = asyncio.Event()
    destination = tmp_path / "partial.txt"
    executor = worker.JobExecutor()
    manager.criar_tarefa(destination, task_id="thread-job")

    def export():
        entered.set()
        assert release.wait(3)
        destination.write_text("complete")

    async def callback():
        try:
            await executor._run_in_executor(export)
        finally:
            destination.unlink(missing_ok=True)
            manager.atualizar("thread-job", status="cancelled")

    async def next_job():
        advanced.set()

    await queue.enqueue(QueueItem(destination, "partial.txt", "test", callback, task_id="thread-job"))
    await queue.enqueue(QueueItem(tmp_path / "next", "next", "test", next_job))
    queue.start_worker()
    try:
        while not entered.is_set():
            await asyncio.sleep(0.01)
        assert worker.cancel_job_status("thread-job")
        assert manager.obter("thread-job")["status"] == "cancelling"
        assert manager.obter("thread-job")["fim"] is None
        await asyncio.wait_for(advanced.wait(), 2)
        assert manager.obter("thread-job")["status"] == "cancelling"
        assert not destination.exists()
        release.set()
        async with asyncio.timeout(2):
            while "thread-job" in queue._active_tasks:
                await asyncio.sleep(0.01)
        assert not destination.exists()
        assert manager.obter("thread-job")["status"] == "cancelled"
    finally:
        release.set()
        await stop_queue(queue)
        executor._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_sqlite_writer_lock_does_not_block_api_loop(isolated_runtime):
    from backend.api.app import create_app
    job_store.load_record("initialize-schema")
    lock = sqlite3.connect(settings.db_path, check_same_thread=False)
    lock.execute("BEGIN IMMEDIATE")
    release = threading.Timer(0.35, lock.commit)
    ticks = []
    finished = asyncio.Event()

    async def heartbeat():
        while not finished.is_set():
            ticks.append(asyncio.get_running_loop().time())
            await asyncio.sleep(0.01)

    release.start()
    pulse = asyncio.create_task(heartbeat())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app()), base_url="http://test") as client:
            response = await client.post("/api/v1/jobs", files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")})
        assert response.status_code == 202
        assert len(ticks) >= 10
        assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.15
    finally:
        finished.set()
        await pulse
        release.join()
        lock.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["enqueue", "persist_before", "persist_after"])
async def test_failed_enqueue_removes_durable_request_and_upload(isolated_runtime, monkeypatch, failure):
    from backend.api.app import create_app
    queue, _ = isolated_runtime

    async def fail_enqueue(item):
        raise RuntimeError("synthetic enqueue failure")

    if failure == "enqueue":
        monkeypatch.setattr(queue, "enqueue", fail_enqueue)
    else:
        original_save = jobs.save_request

        def fail_save(*args):
            if failure == "persist_after":
                original_save(*args)
            raise sqlite3.OperationalError("synthetic persistence failure")

        monkeypatch.setattr(jobs, "save_request", fail_save)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app(), raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post("/api/v1/jobs", files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")})
    assert response.status_code == 500
    assert not list((settings.temp_dir / "uploads").iterdir())
    assert job_store.pending_records() == []
    assert worker.queued_jobs == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("sent", [True, False, None])
async def test_email_delivery_status_does_not_lose_download(
    isolated_runtime, monkeypatch, tmp_path, sent, fake_pdf_ua_audit
):
    _, manager = isolated_runtime
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    job_store.save_request("delivery", "capability", {}, {"status": "queued"})

    async def process(*a, **kw):
        return {"title": "Example", "sections": []}

    def export(document, destination, *a, **kw):
        destination.write_text("output")

    async def audio(text, destination, **kw):
        destination.write_bytes(b"audio")

    async def confirmation(*a):
        return False

    async def result(*a, **kw):
        if sent is None:
            raise OSError("synthetic SMTP failure")
        return sent

    monkeypatch.setattr("backend.service.process", process)
    for name in ["export_txt", "export_docx", "export_pdf_ua", "export_drbench_md", "export_accessible_document"]:
        monkeypatch.setattr(worker, name, export)
    monkeypatch.setattr(worker, "export_mp3", audio)
    monkeypatch.setattr(worker, "send_confirmation_email", confirmation)
    monkeypatch.setattr(worker, "send_result_email", result)
    executor = worker.JobExecutor()
    try:
        await executor.run(worker.ApiJob("delivery", source, "doc.pdf", email="test@example.invalid"))
    finally:
        executor._executor.shutdown(wait=True)
    status = manager.obter("delivery")
    assert status["status"] == "done"
    assert status["download_url"]
    assert status["email_delivery"] == ("sent" if sent else "failed")
    durable = job_store.load_record("delivery")["status"]
    assert durable["download_url"] == status["download_url"]
    assert durable["email_delivery"] == status["email_delivery"]
    assert (settings.data_dir / "output/delivery/doc_acessivel.zip").is_file()


@pytest.mark.asyncio
async def test_result_email_reports_open_obligations_of_a_delivered_document(
    isolated_runtime, monkeypatch, tmp_path, fake_pdf_ua_audit
):
    """A block dropped by fusion is delivered without it; the e-mail says so."""
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    job_store.save_request("open", "capability", {}, {"status": "queued"})
    summary = "Open obligations: rescue-omitted-block (page 3)"

    async def process(*a, **kw):
        return {
            "title": "Example",
            "sections": [],
            "metadata": {"pddl_unsatisfied_summary": summary},
        }

    def export(document, destination, *a, **kw):
        destination.write_text("output")

    async def audio(text, destination, **kw):
        destination.write_bytes(b"audio")

    async def confirmation(*a):
        return False

    warnings: list[str] = []

    async def result(*a, **kw):
        warnings.extend(kw["warnings"])
        return True

    monkeypatch.setattr("backend.service.process", process)
    for name in ["export_txt", "export_docx", "export_pdf_ua", "export_drbench_md", "export_accessible_document"]:
        monkeypatch.setattr(worker, name, export)
    monkeypatch.setattr(worker, "export_mp3", audio)
    monkeypatch.setattr(worker, "send_confirmation_email", confirmation)
    monkeypatch.setattr(worker, "send_result_email", result)
    executor = worker.JobExecutor()
    try:
        await executor.run(worker.ApiJob("open", source, "doc.pdf", email="test@example.invalid"))
    finally:
        executor._executor.shutdown(wait=True)
    assert warnings == [summary]


def test_terminal_job_is_not_overwritten_by_delayed_cancel(isolated_runtime):
    job_store.save_request("race", "secret", {}, {"status": "processing"})
    job_store.save_status("race", {"status": "cancelled", "fim": 10})
    job_store.save_status("race", {"status": "cancelling", "fim": None})
    assert job_store.load_record("race")["status"] == {"status": "cancelled", "fim": 10}


@pytest.mark.asyncio
async def test_cancel_before_callback_entry_releases_slot(tmp_path):
    queue = UnifiedQueue()
    called = []
    path = tmp_path / "pending.pdf"
    path.write_bytes(b"%PDF")

    async def callback():
        called.append(True)

    # Reproduce the dispatch boundary before the event loop enters the callback.
    item = QueueItem(path, "pending.pdf", "test", callback, task_id="boundary")
    task = asyncio.create_task(queue._process_item(item))
    queue._active_items[item.task_id] = item
    queue._active_tasks[item.task_id] = task
    queue._processing_count = 1
    task.add_done_callback(lambda _: queue._finish_item(item.task_id))
    assert queue.cancel(item.task_id)
    await asyncio.gather(task, return_exceptions=True)
    assert queue._processing_count == 0
    assert not queue._active_tasks
    assert not queue.protected_file_paths()
    assert not path.exists()
    assert called == []


@pytest.mark.asyncio
async def test_restart_keeps_download_when_email_delivery_is_unknown(isolated_runtime):
    job_store.save_request("ready", "secret", {}, {"status": "done", "email_delivery": "pending", "download_url": "http://web/download/ready"})
    status = await worker.get_job_status_async("ready")
    assert status["status"] == "done"
    assert status["email_delivery"] == "unknown"
    assert status["download_url"].endswith("/ready")


@pytest.mark.asyncio
async def test_restart_finishes_requested_cancellation(isolated_runtime, tmp_path):
    path = tmp_path / "cancelled.pdf"
    path.write_bytes(b"%PDF")
    job_store.save_request("cancel-restart", "secret", {"file_path": str(path)},
        {"task_id": "cancel-restart", "status": "cancelling"})
    await worker.recover_pending_jobs()
    assert job_store.load_record("cancel-restart")["status"]["status"] == "cancelled"
    assert not path.exists()
    assert isolated_runtime[0].qsize() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["history", "download_token"])
async def test_service_transactions_do_not_block_event_loop(isolated_runtime, tmp_path, operation):
    if operation == "history":
        history_service.init_db()
        transaction = history_service.registrar_conversao("heartbeat", "doc.pdf", ".pdf")
    else:
        download_token_service._get_connection()
        output = tmp_path / "output"
        output.mkdir()
        transaction = download_token_service.criar_token(output, "doc")
    lock = sqlite3.connect(settings.db_path, check_same_thread=False)
    lock.execute("BEGIN IMMEDIATE")
    release = threading.Timer(0.3, lock.commit)
    ticks = 0
    task = asyncio.create_task(transaction)
    release.start()
    try:
        while not task.done():
            ticks += 1
            await asyncio.sleep(0.01)
        await task
        assert ticks >= 10
    finally:
        release.join()
        lock.close()


@pytest.mark.asyncio
async def test_submission_cancellation_does_not_leave_durable_request(isolated_runtime, monkeypatch):
    from backend.api.app import create_app
    entered, release = threading.Event(), threading.Event()
    original_save = jobs.save_request

    def delayed_save(*args):
        entered.set()
        assert release.wait(3)
        original_save(*args)

    monkeypatch.setattr(jobs, "save_request", delayed_save)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app()), base_url="http://test") as client:
        request = asyncio.create_task(client.post("/api/v1/jobs", files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")}))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.01)
            request.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert job_store.pending_records() == []
            assert isolated_runtime[0].qsize() == 0
            assert not list((settings.temp_dir / "uploads").iterdir())
        finally:
            release.set()


@pytest.mark.parametrize("existing", ["queued", "processing", "cancelling", "done", "error", "cancelled"])
@pytest.mark.parametrize("missing", [{}, {"status": None}])
def test_status_without_destination_is_rejected(isolated_runtime, existing, missing):
    job_store.save_request("job", "token", {}, {"status": existing})
    with pytest.raises(ValueError):
        job_store.save_status("job", missing)
    assert job_store.load_record("job")["status"]["status"] == existing


def test_status_persistence_excludes_canonical_result(isolated_runtime):
    job_store.save_request("job", "token", {}, {"status": "queued"})
    status = {"status": "done", "resultado": {"text": "large document"}, "email_delivery": "sent"}
    job_store.save_status("job", status)
    assert job_store.load_record("job")["status"] == {"status": "done", "email_delivery": "sent"}
    assert "resultado" in status


@pytest.mark.asyncio
async def test_queue_status_uses_actual_enqueue_position(isolated_runtime, monkeypatch):
    from backend.api.app import create_app
    from backend.i18n import t
    from backend.stage_messages import STAGE_QUEUE_WAITING_POSITION
    queue, _ = isolated_runtime
    monkeypatch.setattr(queue, "qsize", lambda: 99)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app()), base_url="http://test") as client:
        response = await client.post("/api/v1/jobs", files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")})
    assert response.status_code == 202
    result = response.json()
    assert result["position"] == 1
    expected = t(STAGE_QUEUE_WAITING_POSITION).format(position=1)
    assert worker.get_job_status(result["task_id"])["etapa_atual"] == expected
    assert job_store.load_record(result["task_id"])["status"]["etapa_atual"] == expected
