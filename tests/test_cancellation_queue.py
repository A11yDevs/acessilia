"""Cancellation frees one queue slot while blocking work retains its files."""
import asyncio
import threading

import httpx
import pytest

from backend.api import worker
from backend.services import job_store
from backend.services.blocking import run_blocking
from backend.services.queue_service import QueueItem, UnifiedQueue
from tests.test_pending_fixes import isolated_runtime as runtime_fixture
from tests.test_pending_fixes import stop_queue

isolated_runtime = runtime_fixture


async def wait_until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 3)


@pytest.mark.asyncio
async def test_cancelled_extraction_advances_queue_and_reports_wait(isolated_runtime, monkeypatch, tmp_path):
    from backend.api.app import create_app

    queue, manager = isolated_runtime
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    advanced = asyncio.Event()
    source = tmp_path / "long.pdf"
    source.write_bytes(b"%PDF-long")
    next_source = tmp_path / "next.pdf"
    next_source.write_bytes(b"%PDF-next")
    executor = worker.JobExecutor()

    def extract():
        entered.set()
        assert release.wait(10)
        assert source.read_bytes() == b"%PDF-long"
        finished.set()

    async def process(*args, **kwargs):
        if kwargs["task_id"] == "next":
            from backend.pipeline.canonical_builder import build_canonical_document
            advanced.set()
            return build_canonical_document("Next document.", title="Next")
        await run_blocking(extract)
        pytest.fail("Cancelled extraction must not publish a result")

    async def audio(text, destination, **kwargs):
        destination.write_bytes(b"ID3test")

    from backend.config.settings import settings
    monkeypatch.setattr(settings, "toolbox_docx_enabled", False)
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", False)
    monkeypatch.setattr(worker, "export_mp3", audio)
    monkeypatch.setattr("backend.service.process", process)
    job_store.save_request("long", "test-token", {}, {"task_id": "long", "status": "queued"})
    job_store.save_request("next", "next-token", {}, {"task_id": "next", "status": "queued"})
    await queue.enqueue(QueueItem(source, "long.pdf", "test", executor.run,
        {"job": worker.ApiJob("long", source, "long.pdf")}, task_id="long"))
    await queue.enqueue(QueueItem(next_source, "next.pdf", "test", executor.run,
        {"job": worker.ApiJob("next", next_source, "next.pdf")}, task_id="next"))
    queue.start_worker()
    try:
        await wait_until(entered.is_set)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app()), base_url="http://test") as client:
            response = await client.post("/api/v1/jobs/long/cancel", headers={"X-Job-Token": "test-token"})
            assert response.status_code == 200
            assert response.json()["status"] == "cancelling"
            persisted = job_store.load_record("long")["status"]
            assert persisted["status"] == "cancelling"
            assert persisted["cancellation_requested_at"] == manager.obter("long")["cancellation_requested_at"]
            assert persisted["cancellation_elapsed_seconds"] >= 0
            assert not finished.is_set()
            await asyncio.wait_for(advanced.wait(), 2)
            assert not finished.is_set()
            assert source.exists()
            assert source.resolve() in queue.protected_file_paths()
            task = manager.obter("long")
            assert task["fim"] is None
            task["cancellation_requested_at"] -= 7
            status = (await client.get("/api/v1/jobs/long", headers={"X-Job-Token": "test-token"})).json()
            assert status["cancellation_requested_at"] == task["cancellation_requested_at"]
            assert status["cancellation_elapsed_seconds"] >= 7
            assert str(status["cancellation_elapsed_seconds"]) in status["etapa_atual"]
            assert status["etapa_atual"] != task["etapa_atual"]
        await wait_until(lambda: "next" not in queue._active_tasks)
        assert manager.obter("next")["status"] == "done"
        assert job_store.load_record("next")["status"]["status"] == "done"
        assert not next_source.exists()
        assert not finished.is_set()
        release.set()
        await wait_until(lambda: "long" not in queue._active_tasks)
        assert finished.is_set()
        assert not source.exists()
        assert manager.obter("long")["status"] == "cancelled"
        assert not manager.obter("long").get("download_url")
        assert job_store.load_record("long")["status"]["status"] == "cancelled"
        assert not queue.protected_file_paths()
    finally:
        release.set()
        await stop_queue(queue)
        executor._executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("max_concurrent", [1, 2])
async def test_repeated_cancellations_cannot_start_unbounded_threads(tmp_path, max_concurrent):
    queue = UnifiedQueue(max_concurrent=max_concurrent)
    count = max_concurrent + 2
    entered = [threading.Event() for _ in range(count)]
    release = [threading.Event() for _ in range(count)]

    def block(index):
        entered[index].set()
        assert release[index].wait(10)

    async def callback(index):
        await run_blocking(block, index)

    for index in range(count):
        await queue.enqueue(QueueItem(tmp_path / f"{index}.pdf", f"{index}.pdf", "test",
            callback, {"index": index}, task_id=str(index)))
    queue.start_worker()
    try:
        await wait_until(lambda: all(event.is_set() for event in entered[:max_concurrent]))
        assert not entered[max_concurrent].is_set()
        assert queue.cancel("0")
        await wait_until(entered[max_concurrent].is_set)
        # At N+1 active operations, another cancellation cannot dispatch N+2.
        assert queue.cancel(str(max_concurrent))
        await asyncio.sleep(0.15)
        assert not entered[max_concurrent + 1].is_set()
        assert queue._processing_count == max_concurrent + 1
        assert queue.qsize() == 1
        release[0].set()
        await wait_until(entered[max_concurrent + 1].is_set)
        assert queue._processing_count <= max_concurrent + 1
    finally:
        for event in release:
            event.set()
        await stop_queue(queue)
    assert not queue._active_tasks
    assert queue._processing_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("max_concurrent", [1, 2])
async def test_normal_jobs_keep_the_configured_concurrency(tmp_path, max_concurrent):
    queue = UnifiedQueue(max_concurrent=max_concurrent)
    started = [asyncio.Event() for _ in range(max_concurrent + 1)]
    release = asyncio.Event()

    async def callback(index):
        started[index].set()
        await release.wait()

    for index in range(max_concurrent + 1):
        await queue.enqueue(QueueItem(tmp_path / str(index), str(index), "test",
            callback, {"index": index}))
    queue.start_worker()
    try:
        await wait_until(lambda: all(event.is_set() for event in started[:max_concurrent]))
        await asyncio.sleep(0.15)
        assert not started[max_concurrent].is_set()
        assert queue._processing_count == max_concurrent
        release.set()
        await asyncio.wait_for(started[max_concurrent].wait(), 2)
    finally:
        release.set()
        await stop_queue(queue)


@pytest.mark.parametrize("locale", ["en_US", "pt_BR"])
def test_cancellation_wait_is_localized_and_read_only(isolated_runtime, monkeypatch, tmp_path, locale):
    from backend import i18n
    from backend.stage_messages import STAGE_CANCELLATION_WAITING

    _, manager = isolated_runtime
    manager.criar_tarefa(tmp_path / "input.pdf", task_id="localized")
    token = i18n.set_request_locale(locale)
    try:
        assert manager.cancelar("localized", pending=True)
        task = manager.obter("localized")
        task["cancellation_requested_at"] = 100
        monkeypatch.setattr(worker.time, "time", lambda: 112)
        stage = task["etapa_atual"]
        status = worker.get_job_status("localized")
        assert status["cancellation_elapsed_seconds"] == 12
        assert status["etapa_atual"] == i18n.t(STAGE_CANCELLATION_WAITING).format(seconds=12)
        assert ("waiting" in status["etapa_atual"]) == (locale == "en_US")
        assert task["etapa_atual"] == stage
        assert "cancellation_elapsed_seconds" not in task
        task["status"] = "cancelled"
        assert "cancellation_elapsed_seconds" not in worker.get_job_status("localized")
    finally:
        i18n.reset_request_locale(token)


@pytest.mark.asyncio
async def test_durable_cancellation_wait_is_recomputed_and_cleared(isolated_runtime, monkeypatch):
    stored = {"task_id": "durable", "status": "cancelling", "cancellation_requested_at": 100,
              "cancellation_elapsed_seconds": 999}
    job_store.save_request("durable", "test-token", {}, stored)
    monkeypatch.setattr(worker.time, "time", lambda: 112)
    assert worker.get_job_status("durable")["cancellation_elapsed_seconds"] == 12
    assert (await worker.get_job_status_async("durable"))["cancellation_elapsed_seconds"] == 12
    assert job_store.load_record("durable")["status"]["cancellation_elapsed_seconds"] == 999
    job_store.save_status("durable", {**stored, "status": "cancelled", "fim": 112})
    assert "cancellation_elapsed_seconds" not in worker.get_job_status("durable")
    assert "cancellation_elapsed_seconds" not in await worker.get_job_status_async("durable")
