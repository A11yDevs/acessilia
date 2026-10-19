"""Authorization and restart regressions against the real API contract."""

from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from backend.api.app import create_app
from backend.api.worker import ApiJob, recover_pending_jobs
from backend.config.settings import settings
from backend.services.job_store import load_record, save_request, save_status
from backend.services.queue_service import UnifiedQueue


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(settings, "observability_api_token", "administrator")
    from backend.api import worker
    from backend.api.routes import jobs
    from backend.services import queue_service

    queue = UnifiedQueue()
    monkeypatch.setattr(queue_service, "unified_queue", queue)
    monkeypatch.setattr(jobs, "unified_queue", queue)
    monkeypatch.setattr(worker, "queued_jobs", {})
    from backend.api.limiter import limiter

    monkeypatch.setattr(limiter, "enabled", False)
    return queue


@pytest.mark.asyncio
async def test_job_capability_required_and_not_listed_anonymously(isolated):
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/jobs",
            files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")},
        )
        assert response.status_code == 202
        body = response.json()
        task_id, token = body["task_id"], body["job_token"]
        assert token not in str(load_record(task_id))
        for headers in ({}, {"X-Job-Token": "someone-elses-token"}):
            assert (
                await client.get(f"/api/v1/jobs/{task_id}", headers=headers)
            ).status_code == 404
            assert (
                await client.post(f"/api/v1/jobs/{task_id}/cancel", headers=headers)
            ).status_code == 404
        authorized = {"X-Job-Token": token}
        assert (await client.get(f"/api/v1/jobs/{task_id}", headers=authorized)).json()[
            "status"
        ] == "queued"
        for path in ("history", "stats"):
            assert (await client.get(f"/api/v1/{path}")).status_code == 401
        assert (
            await client.post(f"/api/v1/jobs/{task_id}/cancel", headers=authorized)
        ).status_code == 200


@pytest.mark.asyncio
async def test_durable_queue_and_terminal_status_survive_restart(
    isolated, monkeypatch, tmp_path
):
    from backend.api import worker

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    job = ApiJob("pending", path, "doc.pdf")
    request = asdict(job)
    request["file_path"] = str(path)
    save_request(
        "pending", "capability", request, {"task_id": "pending", "status": "queued"}
    )
    await recover_pending_jobs()
    assert isolated.get_position("pending") == 1
    await recover_pending_jobs()
    assert isolated.qsize() == 1
    save_status(
        "pending", {"task_id": "pending", "status": "done", "download_url": "synthetic"}
    )
    worker.queued_jobs.clear()
    assert worker.get_job_status("pending")["download_url"] == "synthetic"


@pytest.mark.asyncio
async def test_api_rejects_inactive_pipeline_options_before_enqueue(isolated):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/jobs",
            files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")},
            data={"thinking_mode": "true"},
        )
        assert response.status_code == 422
        assert isolated.qsize() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("description", ["A map with two connected regions", "Map", "Logo", "A"])
async def test_ocr_text_is_not_a_visual_description(monkeypatch, description):
    from backend.agents.output_schemas import VisionOutput
    from backend.agents.pddl_orchestrator import _enrich_picture_descriptions
    from tests.test_pddl_orchestrator import _sample_manifest

    manifest = _sample_manifest()
    picture = manifest.elements[1]
    picture.type = "picture"
    picture.text = "North South Ocean"

    class Vision:
        calls = 0

        def __init__(self, **kwargs):
            pass

        async def describe_region(self, **kwargs):
            self.__class__.calls += 1
            return VisionOutput(
                kind="description",
                description=description,
                language="en",
                confidence=0.8,
            )

    monkeypatch.setattr("backend.agents.pddl_orchestrator.VisionAgent", Vision)
    async def crop(_reader, _element, _fallback):
        return b"image", 1

    monkeypatch.setattr(
        "backend.tools.region_extractor.PdfRegionReader.crop", crop
    )
    await _enrich_picture_descriptions(manifest, Path("synthetic.pdf"), mode="normal")
    assert Vision.calls == 1
    assert picture.metadata["vision_description_complete"] is True
    await _enrich_picture_descriptions(manifest, Path("synthetic.pdf"), mode="normal")
    assert Vision.calls == 1


@pytest.mark.asyncio
async def test_interrupted_work_is_terminal_instead_of_replayed(
    isolated, monkeypatch, tmp_path
):
    from backend.services import history_service

    monkeypatch.setattr(history_service, "_connection", None)
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    request = asdict(ApiJob("interrupted", path, "doc.pdf"))
    request["file_path"] = str(path)
    save_request(
        "interrupted",
        "capability",
        request,
        {"task_id": "interrupted", "status": "processing"},
    )
    await recover_pending_jobs()
    assert load_record("interrupted")["status"]["status"] == "error"
    assert isolated.qsize() == 0


def test_second_worker_cannot_claim_same_data_directory(isolated):
    from backend.services.runtime_lease import runtime_lease

    with runtime_lease():
        with pytest.raises(RuntimeError, match="Only one API worker"):
            with runtime_lease():
                pytest.fail("second API worker acquired queue lease")
    with runtime_lease():
        pass


@pytest.mark.asyncio
async def test_frontend_client_sends_job_capability(tmp_path):
    import respx

    from frontend.clients.api_client import ApiClient

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    client = ApiClient("https://api.test")
    with respx.mock:
        respx.post("https://api.test/api/v1/jobs").respond(
            202, json={"task_id": "owner", "job_token": "secret", "position": 1}
        )
        status = respx.get("https://api.test/api/v1/jobs/owner").respond(
            200, json={"status": "queued"}
        )
        cancel = respx.post("https://api.test/api/v1/jobs/owner/cancel").respond(
            200, json={"status": "cancelled"}
        )
        await client.submit_job(path, "doc.pdf")
        await client.get_job_status("owner")
        await client.cancel_job("owner")
        assert status.calls[0].request.headers["X-Job-Token"] == "secret"
        assert cancel.calls[0].request.headers["X-Job-Token"] == "secret"
