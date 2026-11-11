"""How the availability gate reads the Toolbox catalogue (#402, step 3).

Characterization of the transport: the catalogue is read from
``TOOLBOX_BASE_URL`` only (not ``TOOLBOX_BASE_URLS``), with the core's API key,
a 10 s budget per request instead of the extraction timeout, and no retries.
A failed read never raises out of the gate: the cache records it and the gate
reports it as ``catalog_error``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import ToolboxProviderUnavailable, ToolboxTimeout
from backend.config.settings import settings
from backend.core.planning import toolbox_gate

PRIMARY = "http://toolbox-a.test"
SECONDARY = "http://toolbox-b.test"
CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "toolbox-contract.json").read_text(encoding="utf-8")
)


@pytest.fixture(autouse=True)
def catalogue_settings(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_base_url", PRIMARY)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_api_key", "core-key")
    monkeypatch.setattr(settings, "toolbox_timeout_seconds", 3600.0)
    monkeypatch.setattr(settings, "toolbox_retries", 3)
    monkeypatch.setattr(toolbox_gate, "_cache", None)


def _serve(router: respx.MockRouter, base_url: str) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(payload):
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=payload)

        return handler

    router.get(f"{base_url}/v1/capabilities").mock(side_effect=record(CONTRACT["capabilities"]))
    router.get(f"{base_url}/v1/providers").mock(side_effect=record(CONTRACT["providers"]))
    return seen


@pytest.mark.asyncio
async def test_the_catalogue_is_read_from_toolbox_base_url_with_the_core_key() -> None:
    with respx.mock(assert_all_called=False) as router:
        seen = _serve(router, PRIMARY)
        snapshot = await toolbox_gate._fetch()

    assert snapshot.capabilities
    assert seen
    assert {str(request.url.copy_with(path="/")) for request in seen} == {f"{PRIMARY}/"}
    assert all(r.headers["Authorization"] == "Bearer core-key" for r in seen)


@pytest.mark.asyncio
async def test_toolbox_base_urls_does_not_change_the_catalogue_endpoint(monkeypatch) -> None:
    """Reading from every configured endpoint is a separate change (#402)."""
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{SECONDARY},{PRIMARY}")
    with respx.mock(assert_all_called=False) as router:
        primary = _serve(router, PRIMARY)
        secondary = _serve(router, SECONDARY)
        await toolbox_gate._fetch()

    assert primary
    assert secondary == []


@pytest.mark.asyncio
async def test_a_trailing_slash_in_the_url_is_ignored(monkeypatch) -> None:
    monkeypatch.setattr(settings, "toolbox_base_url", f"{PRIMARY}/")
    with respx.mock() as router:
        seen = _serve(router, PRIMARY)
        await toolbox_gate._fetch()

    assert [r.url.path for r in seen][:2] == ["/v1/capabilities", "/v1/providers"]


@pytest.mark.asyncio
async def test_each_request_gets_the_catalogue_budget_not_the_extraction_one() -> None:
    with respx.mock() as router:
        seen = _serve(router, PRIMARY)
        await toolbox_gate._fetch()

    budgets = {
        key: value
        for request in seen
        for key, value in request.extensions["timeout"].items()
    }
    assert set(budgets.values()) == {toolbox_gate.CATALOG_TIMEOUT_SECONDS}
    assert toolbox_gate.CATALOG_TIMEOUT_SECONDS == 10.0


@pytest.mark.asyncio
async def test_a_timeout_is_not_retried() -> None:
    calls = 0

    def timeout(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    with respx.mock() as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(side_effect=timeout)
        with pytest.raises(ToolboxTimeout):
            await toolbox_gate._fetch()

    assert calls == 1


@pytest.mark.asyncio
async def test_an_unreachable_toolbox_is_a_typed_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with respx.mock() as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(side_effect=refuse)
        with pytest.raises(ToolboxProviderUnavailable):
            await toolbox_gate._fetch()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["", "toolbox-without-scheme"])
async def test_an_unusable_url_is_recorded_by_the_cache_not_raised(monkeypatch, url) -> None:
    monkeypatch.setattr(settings, "toolbox_base_url", url)

    cache = toolbox_gate.catalog_cache()
    snapshot = await cache.get()

    assert snapshot is None
    assert cache.last_error is not None
    assert cache.last_error.startswith("ToolboxProviderUnavailable: ")
