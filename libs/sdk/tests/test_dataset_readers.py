"""HTTP consumer tests for additive dataset REST bindings."""

import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from acessilia_sdk.toolbox.clients.dataset import (
    ToolboxDatasetClient,
    SYNC_MIN_TIMEOUT_SECONDS,
)
from acessilia_sdk.toolbox.errors import (
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxError,
)
from acessilia_sdk.toolbox.results import datasets

BASE = "http://toolbox"
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/dataset-results.json").read_text()
)


@pytest_asyncio.fixture
async def client():
    instance = ToolboxDatasetClient(base_url=BASE)
    yield instance
    await instance.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,verb,path,args,record,collection",
    [
        ("list_datasets_result", "GET", "/v1/datasets", {}, "DatasetInfo", True),
        (
            "describe_dataset_result",
            "GET",
            "/v1/datasets/d",
            {"dataset_id": "d"},
            "DatasetInfo",
            False,
        ),
        (
            "list_splits_result",
            "GET",
            "/v1/datasets/d/splits",
            {"dataset_id": "d"},
            "SplitInfo",
            True,
        ),
        (
            "list_items_result",
            "GET",
            "/v1/datasets/d/splits/s/items",
            {"dataset_id": "d", "split": "s"},
            "ItemSummary",
            True,
        ),
        (
            "get_item_result",
            "GET",
            "/v1/datasets/d/splits/s/items/i",
            {"dataset_id": "d", "split": "s", "item_id": "i"},
            "DatasetItem",
            False,
        ),
        (
            "sample_dataset_result",
            "GET",
            "/v1/datasets/d/splits/s/sample",
            {"dataset_id": "d", "split": "s"},
            "DatasetItem",
            True,
        ),
        (
            "sync_dataset_result",
            "POST",
            "/v1/datasets/d/sync",
            {"dataset_id": "d"},
            "DatasetSyncEntry",
            True,
        ),
    ],
)
async def test_typed_routes_use_precise_response_shapes(
    respx_mock, client, method, verb, path, args, record, collection
):
    example = EXAMPLES[record]
    payload = [example] if collection else example
    route = respx_mock.request(verb, BASE + path).mock(
        return_value=httpx.Response(200, json=payload)
    )
    response = await getattr(client, method)(**args)
    model = response[0] if collection else response
    assert isinstance(model, getattr(datasets, record))
    assert model.to_dict() == example
    if method == "sync_dataset_result":
        assert (
            route.calls.last.request.extensions["timeout"]["read"]
            >= SYNC_MIN_TIMEOUT_SECONDS
        )
    if collection:
        route.mock(return_value=httpx.Response(200, json=[]))
        assert await getattr(client, method)(**args) == []
    route.mock(return_value=httpx.Response(200, json={"invalid": True}))
    with pytest.raises(ToolboxContractViolation):
        await getattr(client, method)(**args)
    route.mock(return_value=httpx.Response(500, json={"detail": "listing failed"}))
    with pytest.raises(ToolboxError) as failure:
        await getattr(client, method)(**args)
    assert type(failure.value) is ToolboxError


@pytest.mark.asyncio
async def test_typed_pagination_keeps_bounds_revision_and_failed_page(
    respx_mock, client
):
    calls = []

    def serve(request):
        params = request.url.params
        calls.append(dict(params))
        offset = int(params["offset"])
        return httpx.Response(
            200,
            json=[
                {**EXAMPLES["ItemSummary"], "id": str(offset + i)}
                for i in range(min(int(params["limit"]), 5 - offset))
            ],
        )

    route = respx_mock.get(BASE + "/v1/datasets/d/splits/s/items").mock(
        side_effect=serve
    )
    items = await client.list_all_items_result(
        "d", "s", revision="r1", limit=5, page_size=2
    )
    assert [item.id for item in items] == ["0", "1", "2", "3", "4"]
    assert [(p["limit"], p["offset"], p["revision"]) for p in calls] == [
        ("2", "0", "r1"),
        ("2", "2", "r1"),
        ("1", "4", "r1"),
    ]
    route.mock(
        side_effect=[
            httpx.Response(200, json=[EXAMPLES["ItemSummary"]] * 2),
            httpx.Response(400, json={"detail": "failed page"}),
        ]
    )
    with pytest.raises(ToolboxCapabilityError):
        await client.list_all_items_result("d", "s", page_size=2)


@pytest.mark.asyncio
async def test_sync_keeps_legacy_raw_object_while_typed_reader_requires_array(
    respx_mock, client
):
    route = respx_mock.post(BASE + "/v1/datasets/d/sync").mock(
        return_value=httpx.Response(200, json={"synced": 2})
    )
    assert await client.sync_dataset("d") == {"synced": 2}
    with pytest.raises(ToolboxContractViolation):
        await client.sync_dataset_result("d")
    for report in (
        [],
        [{"status": "skipped", "reason": "mirroring disabled"}],
        [{"status": "skipped", "item": "i", "reason": "missing item"}],
    ):
        route.mock(return_value=httpx.Response(200, json=report))
        assert [
            entry.to_dict() for entry in await client.sync_dataset_result("d")
        ] == report


def test_shared_records_preserve_open_metadata_nulls_and_presence():
    item = datasets.read_dataset_sample([EXAMPLES["DatasetItem"]])[0]
    assert isinstance(item.artifacts[0], datasets.DatasetArtifactRef)
    assert isinstance(item.annotations[0], datasets.DatasetArtifactRef)
    assert item.to_dict() == EXAMPLES["DatasetItem"]
    missing = datasets.DatasetInfo.from_dict(
        {k: v for k, v in EXAMPLES["DatasetInfo"].items() if k != "license"}
    )
    assert missing.license is None and "license" not in missing.to_dict()
    assert (
        datasets.read_dataset_list([EXAMPLES["DatasetInfo"]])[0].to_dict()["license"]
        is None
    )
    assert not hasattr(item.artifacts[0], "digest")


@pytest.mark.asyncio
async def test_typed_pagination_rejects_malformed_page_before_requesting_more(
    respx_mock, client
):
    route = respx_mock.get(BASE + "/v1/datasets/d/splits/s/items").mock(
        return_value=httpx.Response(200, json={"unexpected": "object"})
    )
    with pytest.raises(ToolboxContractViolation):
        await client.list_all_items_result("d", "s", page_size=1)
    assert route.call_count == 1
