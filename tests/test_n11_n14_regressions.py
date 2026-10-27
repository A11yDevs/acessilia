"""Readiness contracts and early rejection of empty job uploads."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.api import worker
from backend.api.limiter import limiter
from backend.api.routes import health, jobs
from backend.config.settings import settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [[], None, "ready", 1, True, {}, {"status": "unavailable"}]
)
@pytest.mark.parametrize("fallback", [False, True])
async def test_readiness_rejects_invalid_contract_and_tries_next_endpoint(
    monkeypatch, body, fallback
):
    original = httpx.AsyncClient
    seen = []

    def upstream(request):
        seen.append(request.url.host)
        return httpx.Response(
            200,
            content=json.dumps(
                {"status": "ready"} if request.url.host == "second.test" else body
            ).encode(),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr(
        settings,
        "toolbox_base_urls",
        "http://first.test,http://second.test" if fallback else "http://first.test",
    )
    monkeypatch.setattr(settings, "fusion_mode", "single")
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs),
    )
    app = FastAPI()
    app.include_router(health.router)
    async with original(
        transport=httpx.ASGITransport(app, raise_app_exceptions=False),
        base_url="http://core.test",
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == (200 if fallback else 503)
    assert seen == (["first.test", "second.test"] if fallback else ["first.test"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,filename,expected",
    [
        (b"", "input.pdf", 400),
        (b"%PDF-fixture", "input.pdf", 202),
        (b"x" * 33, "input.pdf", 413),
        (b"<p>HTML</p>", "input.html", 202),
        (b"", "input.html", 400),
    ],
)
async def test_upload_rejects_empty_and_oversized_before_persistence_or_queue(
    tmp_path, monkeypatch, payload, filename, expected
):
    queued, persisted = [], []

    async def enqueue(item):
        queued.append(item)
        return len(queued)

    monkeypatch.setattr(settings, "temp_dir", tmp_path)
    monkeypatch.setattr(settings, "max_file_size_mb", 32 / (1024 * 1024))
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(
        jobs, "unified_queue", SimpleNamespace(qsize=lambda: 0, enqueue=enqueue)
    )
    monkeypatch.setattr(worker, "queued_jobs", {})
    monkeypatch.setattr(jobs, "save_request", lambda *args: persisted.append(args[0]))
    monkeypatch.setattr(jobs, "save_status", lambda *args: None)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(jobs.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://core.test"
    ) as client:
        response = await client.post(
            "/jobs",
            files={
                "document_file": (
                    filename,
                    payload,
                    "text/html" if filename.endswith(".html") else "application/pdf",
                )
            },
        )
    assert response.status_code == expected
    assert len(queued) == len(persisted) == (1 if expected == 202 else 0)
    paths = list((tmp_path / "uploads").iterdir())
    assert len(paths) == (1 if expected == 202 else 0)
    if expected == 202:
        assert paths[0].read_bytes() == payload
