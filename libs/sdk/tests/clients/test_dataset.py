"""ToolboxDatasetClient and the REST path of the client base (failover included)."""

from __future__ import annotations

import httpx
import respx
import pytest

from acessilia_sdk.toolbox import (
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxIncompatibleEndpoint,
    ToolboxUnavailable,
)
from acessilia_sdk.toolbox.clients import ToolboxDatasetClient
from acessilia_sdk.toolbox.clients.dataset import SYNC_MIN_TIMEOUT_SECONDS

BASE_URL = "http://localhost:8002"
SECONDARY = "http://toolbox-b.test"
ITEMS = f"{BASE_URL}/v1/datasets/dr-docbench/splits/dev/items"


@pytest.fixture
def client() -> ToolboxDatasetClient:
    return ToolboxDatasetClient(base_url=BASE_URL, timeout_seconds=30)


@pytest.mark.asyncio
async def test_list_items_sends_pagination_and_revision(respx_mock, client):
    route = respx_mock.get(ITEMS).mock(return_value=httpx.Response(200, json=[{"id": "1"}]))

    items = await client.list_items("dr-docbench", "dev", revision="r1", limit=5, offset=10)

    assert items == [{"id": "1"}]
    params = route.calls.last.request.url.params
    assert (params["limit"], params["offset"], params["revision"]) == ("5", "10", "r1")


@pytest.mark.asyncio
async def test_routes_without_revision_send_no_params(respx_mock, client):
    route = respx_mock.get(f"{BASE_URL}/v1/datasets/dr-docbench").mock(
        return_value=httpx.Response(200, json={"id": "dr-docbench"})
    )

    assert (await client.describe_dataset("dr-docbench"))["id"] == "dr-docbench"
    assert not route.calls.last.request.url.params


@pytest.mark.asyncio
async def test_get_item_and_sample(respx_mock, client):
    respx_mock.get(f"{ITEMS}/p1").mock(return_value=httpx.Response(200, json={"id": "p1"}))
    sample = respx_mock.get(f"{BASE_URL}/v1/datasets/dr-docbench/splits/dev/sample").mock(
        return_value=httpx.Response(200, json=[])
    )

    assert (await client.get_item("dr-docbench", "dev", "p1"))["id"] == "p1"
    assert await client.sample_dataset("dr-docbench", "dev", n=3) == []
    assert sample.calls.last.request.url.params["n"] == "3"


@pytest.mark.asyncio
async def test_list_datasets_and_splits(respx_mock, client):
    respx_mock.get(f"{BASE_URL}/v1/datasets").mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(f"{BASE_URL}/v1/datasets/d/splits").mock(
        return_value=httpx.Response(200, json=[{"name": "dev"}])
    )

    assert await client.list_datasets() == []
    assert await client.list_splits("d") == [{"name": "dev"}]


@pytest.mark.asyncio
async def test_get_dataset_artifact_returns_bytes(respx_mock, client):
    respx_mock.get(f"{ITEMS}/p1/artifacts/page.png").mock(
        return_value=httpx.Response(200, content=b"\x89PNG")
    )

    assert await client.get_dataset_artifact("dr-docbench", "dev", "p1", "page.png") == b"\x89PNG"


@pytest.mark.asyncio
async def test_sync_uses_a_long_timeout_and_its_params(respx_mock, client):
    route = respx_mock.post(f"{BASE_URL}/v1/datasets/d/sync").mock(
        return_value=httpx.Response(200, json={"synced": 2})
    )

    assert await client.sync_dataset("d", revision="r", split="dev") == {"synced": 2}

    request = route.calls.last.request
    assert dict(request.url.params) == {"revision": "r", "split": "dev"}
    assert request.extensions["timeout"]["read"] == SYNC_MIN_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_invalid_json_is_a_contract_violation(respx_mock, client):
    respx_mock.get(f"{BASE_URL}/v1/datasets").mock(
        return_value=httpx.Response(200, text="<html>")
    )
    with pytest.raises(ToolboxContractViolation, match="not valid JSON"):
        await client.list_datasets()


@pytest.mark.asyncio
async def test_rest_routes_must_be_registered(client):
    with pytest.raises(ToolboxCapabilityError):
        await client._request_on("GET", "/v1/x", capability_id="document.ocr")


def _publish(router, base_url: str, capabilities: list[dict]) -> None:
    router.get(f"{base_url}/v1/capabilities").mock(
        return_value=httpx.Response(200, json=capabilities)
    )
    router.get(f"{base_url}/v1/providers").mock(return_value=httpx.Response(200, json=[]))


@pytest.mark.asyncio
async def test_rest_calls_fail_over_to_a_publishing_secondary():
    client = ToolboxDatasetClient(endpoints=[BASE_URL, SECONDARY])
    try:
        with respx.mock() as router:
            router.get(f"{BASE_URL}/v1/datasets").mock(side_effect=httpx.ConnectError("a"))
            _publish(router, SECONDARY, [{"id": "dataset.list", "version": 1}])
            router.get(f"{SECONDARY}/v1/datasets").mock(
                return_value=httpx.Response(200, json=[{"id": "d"}])
            )
            assert await client.list_datasets() == [{"id": "d"}]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rest_calls_skip_a_secondary_that_does_not_publish_the_route():
    client = ToolboxDatasetClient(endpoints=[BASE_URL, SECONDARY])
    try:
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{BASE_URL}/v1/datasets").mock(side_effect=httpx.ConnectError("a"))
            _publish(router, SECONDARY, [])
            secondary = router.get(f"{SECONDARY}/v1/datasets")
            with pytest.raises(ToolboxUnavailable) as info:
                await client.list_datasets()
        assert not secondary.called
        assert isinstance(info.value.causes[1][1], ToolboxIncompatibleEndpoint)
    finally:
        await client.close()
