"""Retries and failover apply only to idempotent capabilities (ADR-0006, #406).

A read timeout does not tell the client whether the operation ran, and
independent deployments share no deduplication, so after a timeout or an
unavailable instance a non-idempotent call is neither re-sent to the same
endpoint nor moved to another one. The registry's ``idempotent`` decides, per
call: one client instance serves ``dataset.sample`` (not idempotent) and
``dataset.sync`` (idempotent).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import (
    ToolboxCapabilityClient,
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    parse_endpoints,
)
from acessilia_sdk.toolbox import capabilities as registry
from acessilia_sdk.toolbox import client as client_module
from acessilia_sdk.toolbox.clients import ToolboxDatasetClient

PRIMARY = "http://toolbox-a.test"
SECONDARY = "http://toolbox-b.test"
SAMPLE = "/v1/datasets/demo/splits/test/sample"
SYNC = "/v1/datasets/demo/sync"
EXECUTE = "/v1/capabilities/document.ocr:execute"
SUCCEEDED = {"status": "succeeded", "document": {}}


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """Record backoff delays instead of waiting."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(client_module, "_sleep", fake_sleep)
    return delays


def _publish(router: respx.MockRouter, base_url: str, *capabilities: str) -> None:
    router.get(f"{base_url}/v1/capabilities").mock(
        return_value=httpx.Response(
            200, json=[{"id": capability, "version": 1} for capability in capabilities]
        )
    )
    router.get(f"{base_url}/v1/providers").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "docling-ocr", "capabilities": ["document.ocr"]}],
        )
    )


def test_the_registry_marks_dataset_sample_as_the_only_non_idempotent_capability() -> None:
    assert [c.id for c in registry.TOOLBOX_CAPABILITIES.values() if not c.idempotent] == [
        "dataset.sample"
    ]


# ── A non-idempotent capability: one attempt, one endpoint ─────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (httpx.ReadTimeout("slow"), ToolboxTimeout),
        (httpx.ConnectError("refused"), ToolboxProviderUnavailable),
    ],
)
async def test_a_non_idempotent_call_is_not_retried(sleeps, failure, error) -> None:
    """Review of #406: with retries=1, dataset.sample was sent twice after a timeout."""
    client = ToolboxDatasetClient(base_url=PRIMARY, retries=1)
    try:
        with respx.mock() as router:
            route = router.get(PRIMARY + SAMPLE).mock(
                side_effect=[failure, httpx.Response(200, json=[{"id": "x"}])]
            )
            with pytest.raises(error):
                await client.sample_dataset("demo", "test")
        assert route.call_count == 1
        assert sleeps == []
        assert client.retries == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_non_idempotent_call_does_not_fail_over(sleeps) -> None:
    """Review of #406: with two endpoints, a timeout sent dataset.sample again elsewhere."""
    failovers = []
    client = ToolboxDatasetClient(
        endpoints=parse_endpoints(f"{PRIMARY}, {SECONDARY}"),
        retries=1,
        on_failover=lambda endpoint, error: failovers.append(endpoint.base_url),
    )
    try:
        with respx.mock(assert_all_called=False) as router:
            primary = router.get(PRIMARY + SAMPLE).mock(side_effect=httpx.ReadTimeout("slow"))
            catalogue = router.get(SECONDARY + "/v1/capabilities")
            secondary = router.get(SECONDARY + SAMPLE).mock(
                return_value=httpx.Response(200, json=[{"id": "x"}])
            )
            with pytest.raises(ToolboxTimeout) as raised:
                await client.sample_dataset("demo", "test")
        # The error of the attempt actually made, not a combined ToolboxUnavailable
        # naming an endpoint that was never tried.
        assert type(raised.value) is ToolboxTimeout
        assert (primary.call_count, catalogue.call_count, secondary.call_count) == (1, 0, 0)
        assert failovers == []
        assert sleeps == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_non_idempotent_execute_capability_gets_one_attempt(monkeypatch, sleeps) -> None:
    """The :execute path follows the same rule (no registered capability needs it yet)."""
    monkeypatch.setitem(
        registry.TOOLBOX_CAPABILITIES,
        "document.ocr",
        replace(registry.TOOLBOX_CAPABILITIES["document.ocr"], idempotent=False),
    )

    class OcrClient(ToolboxCapabilityClient):
        provider_key = "toolbox_ocr_provider"

    client = OcrClient(endpoints=parse_endpoints(f"{PRIMARY}, {SECONDARY}"), retries=2)
    try:
        with respx.mock(assert_all_called=False) as router:
            primary = router.post(PRIMARY + EXECUTE).mock(side_effect=httpx.ReadTimeout("slow"))
            secondary = router.post(SECONDARY + EXECUTE).mock(
                return_value=httpx.Response(200, json=SUCCEEDED)
            )
            with pytest.raises(ToolboxTimeout):
                await client._execute("document.ocr", artifact_id="a1")
        assert (primary.call_count, secondary.call_count) == (1, 0)
        assert sleeps == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_non_idempotent_call_that_succeeds_is_unchanged(sleeps) -> None:
    client = ToolboxDatasetClient(base_url=PRIMARY, retries=1)
    try:
        with respx.mock() as router:
            router.get(PRIMARY + SAMPLE).mock(return_value=httpx.Response(200, json=[{"id": "x"}]))
            assert await client.sample_dataset("demo", "test") == [{"id": "x"}]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_contract_errors_are_still_not_retried_for_a_non_idempotent_call(sleeps) -> None:
    client = ToolboxDatasetClient(base_url=PRIMARY, retries=1)
    try:
        with respx.mock() as router:
            route = router.get(PRIMARY + SAMPLE).mock(
                return_value=httpx.Response(200, content=b"not json")
            )
            with pytest.raises(ToolboxContractViolation):
                await client.sample_dataset("demo", "test")
        assert route.call_count == 1
    finally:
        await client.close()


# ── An idempotent capability keeps its retries, backoff and failover ───────


@pytest.mark.asyncio
async def test_an_idempotent_rest_call_keeps_its_retries_and_backoff(sleeps) -> None:
    client = ToolboxDatasetClient(base_url=PRIMARY, retries=1, retry_backoff_seconds=1.0)
    try:
        with respx.mock() as router:
            route = router.post(PRIMARY + SYNC).mock(
                side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": True})]
            )
            assert await client.sync_dataset("demo") == {"ok": True}
        assert route.call_count == 2
        assert len(sleeps) == 1 and 0.5 <= sleeps[0] <= 1.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_an_idempotent_rest_call_keeps_its_failover(sleeps) -> None:
    failovers = []
    client = ToolboxDatasetClient(
        endpoints=parse_endpoints(f"{PRIMARY}, {SECONDARY}"),
        on_failover=lambda endpoint, error: failovers.append(endpoint.base_url),
    )
    try:
        with respx.mock() as router:
            router.post(PRIMARY + SYNC).mock(side_effect=httpx.ReadTimeout("slow"))
            _publish(router, SECONDARY, "dataset.sync")
            secondary = router.post(SECONDARY + SYNC).mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            assert await client.sync_dataset("demo") == {"ok": True}
        assert secondary.call_count == 1
        assert failovers == [PRIMARY]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_an_idempotent_execute_call_keeps_its_retries_and_failover(sleeps) -> None:
    class OcrClient(ToolboxCapabilityClient):
        provider_key = "toolbox_ocr_provider"

    client = OcrClient(endpoints=parse_endpoints(f"{PRIMARY}, {SECONDARY}"), retries=1)
    try:
        with respx.mock() as router:
            primary = router.post(PRIMARY + EXECUTE).mock(side_effect=httpx.ReadTimeout("slow"))
            _publish(router, SECONDARY, "document.ocr")
            secondary = router.post(SECONDARY + EXECUTE).mock(
                return_value=httpx.Response(200, json=SUCCEEDED)
            )
            assert await client._execute("document.ocr", artifact_id="a1") == SUCCEEDED
        assert (primary.call_count, secondary.call_count) == (2, 1)
        assert len(sleeps) == 1
    finally:
        await client.close()


# ── One instance, both kinds of call, at the same time ─────────────────────


@pytest.mark.asyncio
async def test_one_client_serves_both_kinds_concurrently(sleeps) -> None:
    """The policy travels with each call; the shared ``retries`` never changes."""
    client = ToolboxDatasetClient(base_url=PRIMARY, retries=1)
    try:
        with respx.mock() as router:
            sample = router.get(PRIMARY + SAMPLE).mock(side_effect=httpx.ReadTimeout("slow"))
            sync = router.post(PRIMARY + SYNC).mock(
                side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": True})]
            )
            results = await asyncio.gather(
                client.sample_dataset("demo", "test"),
                client.sync_dataset("demo"),
                return_exceptions=True,
            )
        assert isinstance(results[0], ToolboxTimeout)
        assert results[1] == {"ok": True}
        assert (sample.call_count, sync.call_count) == (1, 2)
        assert client.retries == 1
    finally:
        await client.close()
