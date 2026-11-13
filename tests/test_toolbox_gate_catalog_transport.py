"""How the availability gate reads the Toolbox catalogue (#402, step 3).

The catalogue is read from the capability clients' primary endpoint: the first
of ``TOOLBOX_BASE_URLS``, else ``TOOLBOX_BASE_URL``, with the core's API key.
That is the deployment every capability call goes to first. There is no
failover for the catalogue: a secondary's snapshot would admit methods that
execution still sends to the primary (#429). Each read has a 10 s budget per
request instead of the extraction timeout, and no retries. A failed read
never raises out of the gate: the cache records it and the gate reports it as
``catalog_error``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import ToolboxCapabilityError, ToolboxProviderUnavailable, ToolboxTimeout
from acessilia_sdk.toolbox.clients import ToolboxStructureClient
from backend.config.settings import settings
from backend.core.planning import toolbox_gate
from backend.tools import toolbox_client
from backend.tools.toolbox_client import make_toolbox_client
from tests.pddl_support import build_element, build_manifest, build_obligation

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


@pytest.mark.asyncio
async def test_the_catalogue_never_fails_over_to_a_secondary(monkeypatch, failovers) -> None:
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY},{SECONDARY}")
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(side_effect=httpx.ReadTimeout("slow"))
        secondary = _serve(router, SECONDARY)
        with pytest.raises(ToolboxTimeout):
            await toolbox_gate._fetch()

    assert secondary == []
    assert failovers == []


# The gate and the call it admits, end to end (review of #429): the deployment
# whose catalogue decided must be the one the capability client calls.

EXTRACT_ON = "/v1/capabilities/document.structure.extract:execute"


def _single_provider_manifest():
    return build_manifest(
        [build_element("el-1", "paragraph")],
        [build_obligation("fuse-providers", ["el-1"], ["single-provider", "human-review"])],
    )


@pytest.fixture
def enforce_with_two_endpoints(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY},{SECONDARY}")
    monkeypatch.setattr(settings, "toolbox_availability_gate", "enforce")
    monkeypatch.setattr(settings, "toolbox_provider", "docling")
    monkeypatch.setattr(settings, "toolbox_retries", 0)


async def _extract(tmp_path) -> None:
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    client = make_toolbox_client(ToolboxStructureClient)
    try:
        await client.extract_structure(file_path=source)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url", ["http://toolbox.test:bad", "http://toolbox.test:99999"]
)
async def test_a_bad_port_is_a_catalogue_error_not_a_traceback(
    monkeypatch, base_url
) -> None:
    """A port the client cannot use degrades planning, like any other bad URL."""
    monkeypatch.setattr(settings, "toolbox_base_url", base_url)
    monkeypatch.setattr(settings, "toolbox_availability_gate", "enforce")
    monkeypatch.setattr(settings, "toolbox_provider", "docling")

    decision = await toolbox_gate.decide(_single_provider_manifest())

    assert decision.catalog_error is not None
    assert decision.catalog_error.startswith("ToolboxProviderUnavailable: ")
    assert "port between 0 and 65535" in decision.catalog_error
    assert "single-provider" in decision.blocked


@pytest.mark.asyncio
async def test_an_unreadable_primary_catalogue_blocks_what_would_run_there(
    enforce_with_two_endpoints, tmp_path
) -> None:
    """The reviewer's case: A's catalogue times out, B publishes the provider.

    A secondary's snapshot must not admit the method, because execution still
    starts on A, where nothing was checked. The decision stays conservative.
    """
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(side_effect=httpx.ReadTimeout("slow"))
        secondary = _serve(router, SECONDARY)
        execute_on_primary = router.post(f"{PRIMARY}{EXTRACT_ON}").mock(
            return_value=httpx.Response(400, json={"detail": "unsupported provider"})
        )
        decision = await toolbox_gate.decide(_single_provider_manifest())

    assert "single-provider" in decision.blocked
    assert decision.catalog_error is not None
    assert decision.catalog_error.startswith("ToolboxTimeout: ")
    assert secondary == []
    assert not execute_on_primary.called


@pytest.mark.asyncio
async def test_an_admitted_method_executes_on_the_deployment_that_was_checked(
    enforce_with_two_endpoints, tmp_path
) -> None:
    with respx.mock(assert_all_called=False) as router:
        primary = _serve(router, PRIMARY)
        secondary = _serve(router, SECONDARY)
        execute_on_primary = router.post(f"{PRIMARY}{EXTRACT_ON}").mock(
            return_value=httpx.Response(400, json={"detail": "rejected"})
        )
        execute_on_secondary = router.post(f"{SECONDARY}{EXTRACT_ON}")
        decision = await toolbox_gate.decide(_single_provider_manifest())
        with pytest.raises(ToolboxCapabilityError):
            await _extract(tmp_path)

    assert decision.blocked == {}
    assert primary and secondary == []
    assert execute_on_primary.called
    assert not execute_on_secondary.called
