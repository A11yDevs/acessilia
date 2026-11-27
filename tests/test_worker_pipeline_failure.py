from __future__ import annotations

import pytest

from backend.config.settings import settings


@pytest.mark.asyncio
async def test_job_executor_does_not_export_pipeline_failure(tmp_path, monkeypatch):
    import backend.services.history_service as hs
    from backend import service
    from backend.agents.state_manager import state_manager
    from backend.api.worker import ApiJob, JobExecutor

    task_id = "pipeline-failure"
    input_path = tmp_path / "pipeline-failure.pdf"
    output_dir = tmp_path / "output" / task_id
    input_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    hs._connection = None
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()

    async def fail_pipeline(*args, **kwargs):
        raise RuntimeError("orchestrator failed")

    async def fail_if_token_created(*args, **kwargs):
        raise AssertionError("token should not be created after pipeline failure")

    monkeypatch.setattr(service.agente, "execute", fail_pipeline)
    monkeypatch.setattr("backend.api.worker.criar_token", fail_if_token_created)

    from backend.services import job_store

    job_store.save_request(
        task_id,
        "token",
        {"file": str(input_path)},
        {"task_id": task_id, "status": "queued"},
    )

    await JobExecutor().run(
        ApiJob(
            task_id=task_id,
            file_path=input_path,
            filename=input_path.name,
            output_dir=output_dir,
        )
    )

    task = state_manager.obter(task_id)
    assert task is not None
    assert task["status"] == "error"
    # The attempt is recorded before the pipeline starts and its result is
    # filled when it fails, without the error message (#944).
    attempts = job_store.load_attempts(task_id)
    assert len(attempts) == 1
    assert attempts[0]["resumed"] is False
    assert attempts[0]["state"] == "failed"
    assert attempts[0]["origin"] == "unknown"
    assert attempts[0]["error_type"] == "RuntimeError"
    assert attempts[0]["configuration"]["provenance"]["result_origin"] == "unknown"
    assert task.get("download_url") is None
    assert not output_dir.exists()

    rows = await hs.listar_historico(10)
    [row] = [row for row in rows if row["task_id"] == task_id]
    assert row["status"] == "error"
    assert "orchestrator failed" in row["erro"]
