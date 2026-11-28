"""Cancellation after the final normalization response obeys job publication policy."""

from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from acessilia_core.blocking import run_blocking
from acessilia_sdk.toolbox.clients import ToolboxTextNormalizeClient
from backend.api import worker
from backend.services import job_store
from backend.services.job_checkpoint import FileJobCheckpoints
from backend.services.operation_registry import JobOperations, operation_registry
from backend.services.queue_service import QueueItem
from backend.services.run_ports import checkpoint_options
from tests.differential import runner
from tests.differential.runner import run_case
from tests.test_cancellation_queue import wait_until
from tests.test_pending_fixes import isolated_runtime as runtime_fixture, stop_queue

isolated_runtime = runtime_fixture


@pytest.mark.asyncio
async def test_cancel_after_last_remote_response_can_finish_checkpoint_but_never_publish(
    isolated_runtime, monkeypatch, tmp_path
):
    queue, manager = isolated_runtime
    task_id = "normalization-cancellation"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-cancellation")
    arrived, release, finished = threading.Event(), threading.Event(), threading.Event()
    executions = []
    calls = 0
    original_normalize = ToolboxTextNormalizeClient.normalize

    class Checkpoints(FileJobCheckpoints):
        def save(self, phase, payload):
            super().save(phase, payload)
            if phase == "execution":
                executions.append(deepcopy(payload))

    checkpoints = Checkpoints(task_id, checkpoint_options())
    original_ports = runner._ports

    def host_ports(cls, checkpoint_port):
        return replace(
            original_ports(cls, checkpoint_port), operations=JobOperations(task_id)
        )

    async def last_response(client, *args, **kwargs):
        nonlocal calls
        result = await original_normalize(client, *args, **kwargs)
        calls += 1
        if calls == 2:
            arrived.set()
            assert release.wait(15)
        return result

    def pipeline():
        case = Path(__file__).parent / "differential/cases/text-normalization/case.json"
        try:
            return run_case(case, checkpoints=checkpoints)
        finally:
            finished.set()

    async def process(*_args, **_kwargs):
        await run_blocking(pipeline)
        pytest.fail("the cancelled pipeline cannot publish its canonical result")

    async def publish(*_args, **_kwargs):
        pytest.fail("cancelled normalization cannot publish a download token")

    monkeypatch.setattr(ToolboxTextNormalizeClient, "normalize", last_response)
    monkeypatch.setattr(runner, "_ports", host_ports)
    monkeypatch.setattr("backend.service.process", process)
    monkeypatch.setattr(worker, "criar_token", publish)
    job_store.save_request(
        task_id, "cancel-token", {}, {"task_id": task_id, "status": "queued"}
    )
    executor = worker.JobExecutor()
    await queue.enqueue(
        QueueItem(
            source,
            "source.pdf",
            "test",
            executor.run,
            {"job": worker.ApiJob(task_id, source, "source.pdf")},
            task_id=task_id,
        )
    )
    queue.start_worker()
    try:
        await wait_until(arrived.is_set)
        # Response received, observations not yet accepted. Only the preceding
        # obligation is committed; there is no partial second obligation.
        elements = {
            item["id"]: item
            for item in checkpoints.load("execution")["manifest"]["elements"]
        }
        assert elements["p1"]["metadata"]["norm_fixed"] is True
        assert elements["p2"]["metadata"]["norm_fixed"] is False
        assert len(operation_registry.active(task_id)) == 1
        operation_registry.cancel_task(task_id)
        assert worker.cancel_job_status(task_id)
        assert manager.obter(task_id)["status"] == "cancelling"
        assert not finished.is_set() and source.exists()
        release.set()
        await wait_until(lambda: task_id not in queue._active_tasks)
        assert finished.is_set() and calls == 2
        assert not operation_registry.active(task_id)
        # run_blocking joins a running thread: it may commit the entire final
        # step before cancellation propagates. No rollback is promised.
        final = {item["id"]: item for item in executions[-1]["manifest"]["elements"]}
        assert final["p2"]["metadata"]["norm_fixed"] is True
        assert "ab-\nc" in final["p1"]["text"]
        assert manager.obter(task_id)["status"] == "cancelled"
        assert not manager.obter(task_id).get("download_url")
        assert job_store.load_record(task_id)["status"]["status"] == "cancelled"
        assert checkpoints.load("execution") is None
    finally:
        release.set()
        await stop_queue(queue)
        executor._executor.shutdown(wait=True)
        operation_registry.clear(task_id)
