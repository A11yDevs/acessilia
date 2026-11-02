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
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._extract_picture_bytes",
        lambda *args: (b"image", 1),
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


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["invalid\nrecipient@example.test", "invalid\rrecipient@example.test", "not-an-address", "a@example.test,b@example.test", "a@[", "a@[x"])
async def test_invalid_recipient_is_rejected_before_upload(isolated, email):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/jobs",
            files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")},
            data={"email": email},
        )
    assert response.status_code == 422
    assert isolated.qsize() == 0
    assert not (settings.temp_dir / "uploads").exists()
    assert not settings.db_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locale,expected",
    [
        ("en_US", "Invalid email address"),
        ("pt_BR", "Endere\u00e7o de e-mail inv\u00e1lido"),
    ],
)
async def test_invalid_recipient_error_is_localized(isolated, monkeypatch, tmp_path, locale, expected):
    from backend import i18n
    from scripts.gen_locale_catalogs import build_locales

    catalogs = tmp_path / "locales"
    build_locales(catalogs)
    monkeypatch.setattr(i18n, "LOCALE_CATALOGS_DIR", catalogs)
    i18n._catalog_for.cache_clear()
    token = i18n.set_request_locale(locale)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app()), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/jobs",
                files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")},
                data={"email": "a@["},
            )
        assert response.status_code == 422
        assert response.json() == {"detail": expected}
        assert isolated.qsize() == 0
        assert not (settings.temp_dir / "uploads").exists()
    finally:
        i18n.reset_request_locale(token)
        i18n._catalog_for.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["", "   ", "reader@example.test", "reader+tag@example.test", " reader@example.test "])
async def test_valid_or_optional_recipient_is_accepted(isolated, email):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/jobs",
            files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")},
            data={"email": email},
        )
    assert response.status_code == 202
    assert isolated.qsize() == 1

    record = load_record(response.json()["task_id"])
    assert record["request"]["email"] == (email.strip() or None)


@pytest.mark.asyncio
@pytest.mark.parametrize("unexpected_failure", [False, True])
async def test_notification_failure_does_not_stop_recovery(isolated, monkeypatch, tmp_path, unexpected_failure):
    from unittest.mock import AsyncMock
    from backend.api import worker
    from backend.services import email_service

    monkeypatch.setattr(worker, "finalizar_conversao", AsyncMock())
    monkeypatch.setattr(settings, "smtp_user", "audit@example.test")
    monkeypatch.setattr(settings, "smtp_password", "fake-password")
    smtp = AsyncMock()
    monkeypatch.setattr(email_service.aiosmtplib, "send", smtp)
    if unexpected_failure:
        notification = AsyncMock(side_effect=ValueError("Invalid legacy email header"))
        monkeypatch.setattr(worker, "send_failure_email", notification)
    for task_id, status in [("interrupted-email", "processing"), ("next-job", "queued")]:
        path = tmp_path / f"{task_id}.pdf"
        path.write_bytes(b"%PDF")
        payload = asdict(ApiJob(task_id, path, "doc.pdf", email="invalid\nrecipient@example.test"))
        payload["file_path"] = str(path)
        save_request(task_id, "capability", payload, {"task_id": task_id, "status": status})

    await recover_pending_jobs()

    smtp.assert_not_awaited()
    if unexpected_failure:
        notification.assert_awaited_once()
    assert load_record("interrupted-email")["status"]["status"] == "error"
    assert isolated.get_position("next-job") == 1


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
