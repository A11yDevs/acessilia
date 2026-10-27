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


