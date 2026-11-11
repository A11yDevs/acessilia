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
from acessilia_sdk.toolbox.clients.dataset import MAX_PAGE_SIZE, SYNC_MIN_TIMEOUT_SECONDS

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


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["input/plain.pdf", "input/lesson#1.pdf", "input/lesson?1.pdf", "input/literal%2F.pdf", "input/a b.pdf", "input/álgebra.pdf"])
async def test_dataset_artifact_path_is_encoded_without_changing_filename(respx_mock, client, path):
    from urllib.parse import quote

    route = respx_mock.get(f"{ITEMS}/p1/artifacts/{quote(path, safe='/')}").mock(return_value=httpx.Response(200, content=b"fixture"))
    assert await client.get_dataset_artifact("dr-docbench", "dev", "p1", path) == b"fixture"
    request = route.calls.last.request
    assert request.url.path == "/v1/datasets/dr-docbench/splits/dev/items/p1/artifacts/" + path
    assert not request.url.query
    assert not request.url.fragment


def _serve_items(respx_mock, total: int):
    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params["limit"])
        offset = int(request.url.params["offset"])
        size = max(0, min(limit, total - offset))
        return httpx.Response(200, json=[{"id": str(n)} for n in range(offset, offset + size)])

    return respx_mock.get(ITEMS).mock(side_effect=handler)


def _pages(route) -> list[tuple[str, str]]:
    return [
        (call.request.url.params["limit"], call.request.url.params["offset"])
        for call in route.calls
    ]


@pytest.mark.asyncio
async def test_list_all_items_reads_pages_until_a_short_one(respx_mock, client):
    route = _serve_items(respx_mock, total=2 * MAX_PAGE_SIZE + 5)

    items = await client.list_all_items("dr-docbench", "dev")

    assert [item["id"] for item in items] == [str(n) for n in range(2 * MAX_PAGE_SIZE + 5)]
    assert _pages(route) == [("1000", "0"), ("1000", "1000"), ("1000", "2000")]


@pytest.mark.asyncio
async def test_list_all_items_asks_only_for_what_the_limit_needs(respx_mock, client):
    route = _serve_items(respx_mock, total=50)

    items = await client.list_all_items("dr-docbench", "dev", limit=25, page_size=10)

    assert len(items) == 25
    assert _pages(route) == [("10", "0"), ("10", "10"), ("5", "20")]


@pytest.mark.asyncio
async def test_list_all_items_sends_the_revision_on_every_page(respx_mock, client):
    route = _serve_items(respx_mock, total=15)

    await client.list_all_items("dr-docbench", "dev", revision="r1", page_size=10)

    assert [call.request.url.params["revision"] for call in route.calls] == ["r1", "r1"]


@pytest.mark.asyncio
async def test_list_all_items_with_a_zero_limit_reads_nothing(respx_mock, client):
    route = _serve_items(respx_mock, total=5)

    assert await client.list_all_items("dr-docbench", "dev", limit=0) == []
    assert not route.called


@pytest.mark.asyncio
async def test_list_all_items_raises_a_failed_page_instead_of_a_partial_list(
    respx_mock, client
):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.Response(400, json={"detail": "bad page"})
        return httpx.Response(200, json=[{"id": str(n)} for n in range(10)])

    respx_mock.get(ITEMS).mock(side_effect=handler)

    with pytest.raises(ToolboxCapabilityError):
        await client.list_all_items("dr-docbench", "dev", page_size=10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs", [{"page_size": 0}, {"page_size": MAX_PAGE_SIZE + 1}, {"limit": -1}]
)
async def test_list_all_items_rejects_bad_bounds(client, kwargs):
    with pytest.raises(ValueError):
        await client.list_all_items("dr-docbench", "dev", **kwargs)
