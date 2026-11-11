"""How the availability gate reads the Toolbox catalogue (#402, step 3).

The catalogue is read where the capability clients call: the endpoints of
``TOOLBOX_BASE_URLS`` in order, else ``TOOLBOX_BASE_URL``, with the core's API
key. Each read has a 10 s budget per request instead of the extraction timeout,
and no retries. The next endpoint is tried only when one is unreachable or
times out (ADR-0006), and the snapshot comes whole from one deployment. A
failed read never raises out of the gate: the cache records it and the gate
reports it as ``catalog_error``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    snapshot_from_payloads,
)
from backend.config.settings import settings
from backend.core.planning import toolbox_gate
from backend.tools import toolbox_client

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


def _serve(
    router: respx.MockRouter, base_url: str, providers=None
) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    providers = CONTRACT["providers"] if providers is None else providers

    def record(payload):
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=payload)

        return handler

    router.get(f"{base_url}/v1/capabilities").mock(side_effect=record(CONTRACT["capabilities"]))
    router.get(f"{base_url}/v1/providers").mock(side_effect=record(providers))
    return seen


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


@pytest.fixture
def failovers(monkeypatch) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        toolbox_client,
        "_log_failover",
        lambda endpoint, error: seen.append((endpoint.base_url, type(error).__name__)),
    )
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
async def test_toolbox_base_urls_sets_the_catalogue_endpoint_like_the_clients(
    monkeypatch, failovers
) -> None:
    """The clients call the first of TOOLBOX_BASE_URLS; the gate checks that one."""
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{SECONDARY},{PRIMARY}")
    with respx.mock(assert_all_called=False) as router:
        primary = _serve(router, PRIMARY)
        secondary = _serve(router, SECONDARY)
        await toolbox_gate._fetch()

    assert secondary
    assert primary == []
    assert failovers == []


def _without(provider_id: str) -> list[dict]:
    return [entry for entry in CONTRACT["providers"] if entry["id"] != provider_id]


@pytest.mark.asyncio
async def test_an_unreachable_primary_moves_the_read_to_the_next_endpoint(
    monkeypatch, failovers
) -> None:
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY},{SECONDARY}")
    fewer = _without(CONTRACT["providers"][0]["id"])
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(side_effect=_refuse)
        secondary = _serve(router, SECONDARY, providers=fewer)
        snapshot = await toolbox_gate._fetch()

    expected = snapshot_from_payloads(CONTRACT["capabilities"], fewer, fetched_at=0.0)
    assert snapshot.revision == expected.revision
    assert all(r.headers["Authorization"] == "Bearer core-key" for r in secondary)
    assert failovers == [(PRIMARY, "ToolboxProviderUnavailable")]


@pytest.mark.asyncio
async def test_a_snapshot_never_mixes_two_deployments(monkeypatch, failovers) -> None:
    """The primary's capabilities are dropped when its providers read times out."""
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY},{SECONDARY}")
    fewer = _without(CONTRACT["providers"][0]["id"])
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=CONTRACT["capabilities"])
        )
        router.get(f"{PRIMARY}/v1/providers").mock(side_effect=httpx.ReadTimeout("slow"))
        secondary = _serve(router, SECONDARY, providers=fewer)
        snapshot = await toolbox_gate._fetch()

    assert [r.url.path for r in secondary][:2] == ["/v1/capabilities", "/v1/providers"]
    expected = snapshot_from_payloads(CONTRACT["capabilities"], fewer, fetched_at=0.0)
    assert snapshot.revision == expected.revision
    assert failovers == [(PRIMARY, "ToolboxTimeout")]


@pytest.mark.asyncio
async def test_a_malformed_primary_catalogue_is_not_failed_over(
    monkeypatch, failovers
) -> None:
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY},{SECONDARY}")
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(
            return_value=httpx.Response(200, text="not json")
        )
        secondary = _serve(router, SECONDARY)
        with pytest.raises(ToolboxContractViolation):
            await toolbox_gate._fetch()

    assert secondary == []
    assert failovers == []


@pytest.mark.asyncio
async def test_when_every_endpoint_fails_the_cache_records_every_cause(
    monkeypatch, failovers
) -> None:
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY},{SECONDARY}")
    with respx.mock() as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(side_effect=_refuse)
        router.get(f"{SECONDARY}/v1/capabilities").mock(side_effect=httpx.ReadTimeout("slow"))
        cache = toolbox_gate.catalog_cache()
        snapshot = await cache.get()

    assert snapshot is None
    assert cache.last_error.startswith("ToolboxUnavailable: ")
    assert PRIMARY in cache.last_error and SECONDARY in cache.last_error
    assert [url for url, _ in failovers] == [PRIMARY, SECONDARY]


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
@pytest.mark.parametrize(
    ("url", "urls"),
    [("", ""), ("toolbox-without-scheme", ""), (PRIMARY, "toolbox-without-scheme")],
)
async def test_an_unusable_url_is_recorded_by_the_cache_not_raised(
    monkeypatch, url, urls
) -> None:
    monkeypatch.setattr(settings, "toolbox_base_url", url)
    monkeypatch.setattr(settings, "toolbox_base_urls", urls)

    cache = toolbox_gate.catalog_cache()
    snapshot = await cache.get()

    assert snapshot is None
    assert cache.last_error is not None
    assert cache.last_error.startswith("ToolboxProviderUnavailable: ")
