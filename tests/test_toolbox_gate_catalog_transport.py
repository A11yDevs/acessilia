"""How the availability gate reads the Toolbox catalogue (#402, step 3).

The catalogue is read from the capability clients' primary endpoint: the first
of ``TOOLBOX_BASE_URLS``, else ``TOOLBOX_BASE_URL``, with the API key of the
run's ``ToolboxConfig``.
That is the deployment every capability call goes to first. There is no
failover for the catalogue: a secondary's snapshot would admit methods that
execution still sends to the primary (#429). Each read has a 10 s budget per
request instead of the extraction timeout, and no retries. A failed read
never raises out of the gate: the cache records it and the gate reports it as
``catalog_error``.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

import httpx
import pytest
import respx

from acessilia_core.planning import toolbox_gate
from acessilia_core.toolbox import toolbox_client
from acessilia_core.toolbox.toolbox_client import make_toolbox_client
from acessilia_sdk.toolbox import (
    ToolboxCapabilityError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
)
from acessilia_sdk.toolbox.clients import ToolboxStructureClient
from backend.config.settings import settings
from tests.core_config_support import core_config, toolbox_config
from tests.pddl_support import build_element, build_manifest, build_obligation

PRIMARY = "http://toolbox-a.test"
SECONDARY = "http://toolbox-b.test"
CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "toolbox-contract.json").read_text(encoding="utf-8")
)


@pytest.fixture(autouse=True)
def catalogue_settings(monkeypatch):
    """The settings the capability clients read in the end-to-end tests below."""
    monkeypatch.setattr(settings, "toolbox_base_url", PRIMARY)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_api_key", "core-key")
    monkeypatch.setattr(settings, "toolbox_timeout_seconds", 3600.0)
    monkeypatch.setattr(settings, "toolbox_retries", 3)
    monkeypatch.setattr(toolbox_gate, "_caches", OrderedDict())


def _toolbox(**fields):
    """A run's Toolbox config: the primary endpoint, the core's key, long client budgets."""
    return toolbox_config(**({
        "base_url": PRIMARY,
        "base_urls": "",
        "api_key": "core-key",
        "timeout_seconds": 3600,
        "retries": 3,
    } | fields))


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
        snapshot = await toolbox_gate._fetch(_toolbox())

    assert snapshot.capabilities
    assert seen
    assert {str(request.url.copy_with(path="/")) for request in seen} == {f"{PRIMARY}/"}
    assert all(r.headers["Authorization"] == "Bearer core-key" for r in seen)


@pytest.mark.asyncio
async def test_the_catalogue_is_read_with_the_key_of_the_run_config() -> None:
    with respx.mock(assert_all_called=False) as router:
        seen = _serve(router, PRIMARY)
        await toolbox_gate._fetch(_toolbox(api_key="run-key"))

    assert seen
    assert all(r.headers["Authorization"] == "Bearer run-key" for r in seen)


@pytest.mark.asyncio
async def test_toolbox_base_urls_sets_the_catalogue_endpoint_like_the_clients(
    monkeypatch, failovers
) -> None:
    """The clients call the first of TOOLBOX_BASE_URLS; the gate checks that one."""
    with respx.mock(assert_all_called=False) as router:
        primary = _serve(router, PRIMARY)
        secondary = _serve(router, SECONDARY)
        await toolbox_gate._fetch(_toolbox(base_urls=f"{SECONDARY},{PRIMARY}"))

    assert secondary
    assert primary == []
    assert failovers == []


@pytest.mark.asyncio
async def test_a_trailing_slash_in_the_url_is_ignored() -> None:
    with respx.mock() as router:
        seen = _serve(router, PRIMARY)
        await toolbox_gate._fetch(_toolbox(base_url=f"{PRIMARY}/"))

    assert [r.url.path for r in seen][:2] == ["/v1/capabilities", "/v1/providers"]


@pytest.mark.asyncio
async def test_each_request_gets_the_catalogue_budget_not_the_extraction_one() -> None:
    with respx.mock() as router:
        seen = _serve(router, PRIMARY)
        await toolbox_gate._fetch(_toolbox())

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
            await toolbox_gate._fetch(_toolbox())

    assert calls == 1


@pytest.mark.asyncio
async def test_an_unreachable_toolbox_is_a_typed_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with respx.mock() as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(side_effect=refuse)
        with pytest.raises(ToolboxProviderUnavailable):
            await toolbox_gate._fetch(_toolbox())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "urls"),
    [("", ""), ("toolbox-without-scheme", ""), (PRIMARY, "toolbox-without-scheme")],
)
async def test_an_unusable_url_is_recorded_by_the_cache_not_raised(url, urls) -> None:
    cache = toolbox_gate.catalog_cache(_toolbox(base_url=url, base_urls=urls))
    snapshot = await cache.get()

    assert snapshot is None
    assert cache.last_error is not None
    assert cache.last_error.startswith("ToolboxProviderUnavailable: ")


@pytest.mark.asyncio
async def test_the_catalogue_never_fails_over_to_a_secondary(failovers) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{PRIMARY}/v1/capabilities").mock(side_effect=httpx.ReadTimeout("slow"))
        secondary = _serve(router, SECONDARY)
        with pytest.raises(ToolboxTimeout):
            await toolbox_gate._fetch(_toolbox(base_urls=f"{PRIMARY},{SECONDARY}"))

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
    client = make_toolbox_client(ToolboxStructureClient, toolbox_config())
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

    decision = await toolbox_gate.decide(_single_provider_manifest(), core_config())

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
        decision = await toolbox_gate.decide(_single_provider_manifest(), core_config())

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
        decision = await toolbox_gate.decide(_single_provider_manifest(), core_config())
        with pytest.raises(ToolboxCapabilityError):
            await _extract(tmp_path)

    assert decision.blocked == {}
    assert primary and secondary == []
    assert execute_on_primary.called
    assert not execute_on_secondary.called


# A run whose ToolboxConfig is unlike the settings (ADR-0016 step 3, toolbox
# PR 3): the catalogue the gate reads and every call the clients make use the
# run's deployment, key, provider and retries. The settings point at a
# deployment nothing routes, so a client that read them would fail the test.

ELSEWHERE = "http://settings-only.test"


@pytest.fixture
def run_unlike_the_settings(monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(settings, "toolbox_base_url", ELSEWHERE)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_api_key", "settings-key")
    monkeypatch.setattr(settings, "toolbox_provider", "settings-provider")
    monkeypatch.setattr(settings, "toolbox_retries", 3)
    return replace(
        core_config(),
        toolbox=toolbox_config(
            base_url=PRIMARY,
            base_urls=f"{PRIMARY},{SECONDARY}",
            api_key="run-key",
            retries=0,
            availability_gate="enforce",
            providers={"toolbox_provider": "docling"},
        ),
    )


@pytest.mark.asyncio
async def test_the_gate_and_the_clients_follow_a_run_config_unlike_the_settings(
    run_unlike_the_settings, tmp_path
) -> None:
    config = run_unlike_the_settings
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    with respx.mock(assert_all_called=False) as router:
        catalogue = _serve(router, PRIMARY)
        execute = router.post(f"{PRIMARY}{EXTRACT_ON}").mock(
            return_value=httpx.Response(400, json={"detail": "rejected"})
        )
        decision = await toolbox_gate.decide(_single_provider_manifest(), config)
        client = make_toolbox_client(ToolboxStructureClient, config.toolbox)
        try:
            with pytest.raises(ToolboxCapabilityError):
                await client.extract_structure(file_path=source)
        finally:
            await client.close()

    assert decision.blocked == {}
    assert catalogue and all(r.headers["Authorization"] == "Bearer run-key" for r in catalogue)
    # One call (retries=0), on the run's primary, with its key and provider.
    [call] = execute.calls
    assert call.request.headers["Authorization"] == "Bearer run-key"
    assert b"docling" in call.request.content and b"settings-provider" not in call.request.content


def test_the_client_configuration_is_the_run_config(run_unlike_the_settings) -> None:
    from acessilia_core.toolbox.toolbox_client import toolbox_client_config
    from acessilia_sdk.toolbox.clients import ToolboxDocxClient

    toolbox = replace_timeouts(run_unlike_the_settings.toolbox)
    sdk = toolbox_client_config(toolbox)

    assert [endpoint.base_url for endpoint in sdk.endpoints] == [PRIMARY, SECONDARY]
    assert sdk.api_key == "run-key"
    assert sdk.retries == 0
    assert sdk.providers["toolbox_provider"] == "docling"
    assert sdk.timeouts[ToolboxDocxClient.timeout_key] == 7


def replace_timeouts(toolbox):
    from dataclasses import replace

    from acessilia_sdk.toolbox.clients import ToolboxDocxClient

    return replace(toolbox, timeouts={**toolbox.timeouts, ToolboxDocxClient.timeout_key: 7})
