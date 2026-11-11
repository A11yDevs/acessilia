"""The benchmark harness's Toolbox access (scripts/bench/toolbox.py, #402 step 4).

Characterization: which endpoint, key, timeout, retries and provider the
harness's clients get from the environment, and how the dataset listing is
paged (1000 items per request, ``limit`` honoured, stopping at a short page).
Toolbox errors reach the caller typed; nothing turns them into empty data.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import (
    ToolboxEndpoint,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    make_client,
)
from acessilia_sdk.toolbox.capabilities import provider_default
from acessilia_sdk.toolbox.clients import ToolboxDatasetClient, ToolboxStructureClient
from backend.config.settings import Settings, settings
from backend.tools import toolbox_client
from scripts.bench import toolbox

PRIMARY = "http://toolbox-a.test"
SECONDARY = "http://toolbox-b.test"
DATASET = "dr-docbench"
ITEMS = f"{PRIMARY}/v1/datasets/{DATASET}/splits/dev/items"
EXTRACT = f"{PRIMARY}/v1/capabilities/document.structure.extract:execute"


@pytest.fixture(autouse=True)
def toolbox_env(monkeypatch):
    """The same values in the environment and in the core's settings."""
    values = {
        "toolbox_base_url": ("TOOLBOX_BASE_URL", PRIMARY),
        "toolbox_base_urls": ("TOOLBOX_BASE_URLS", ""),
        "toolbox_api_key": ("TOOLBOX_API_KEY", "bench-key"),
        "toolbox_timeout_seconds": ("TOOLBOX_TIMEOUT_SECONDS", 120),
        "toolbox_retries": ("TOOLBOX_RETRIES", 0),
        "toolbox_retry_backoff_seconds": ("TOOLBOX_RETRY_BACKOFF_SECONDS", 0.25),
        "toolbox_provider": ("TOOLBOX_PROVIDER", provider_default("toolbox_provider")),
    }
    for attribute, (variable, value) in values.items():
        monkeypatch.setattr(settings, attribute, value)
        monkeypatch.setenv(variable, str(value))


def _page(start: int, size: int) -> list[dict]:
    return [{"id": f"item-{n}"} for n in range(start, start + size)]


def _serve_items(router: respx.MockRouter, total: int) -> respx.Route:
    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params["limit"])
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json=_page(offset, max(0, min(limit, total - offset))))

    return router.get(ITEMS).mock(side_effect=handler)


def _pages_requested(route: respx.Route) -> list[tuple[int, int]]:
    return [
        (int(call.request.url.params["limit"]), int(call.request.url.params["offset"]))
        for call in route.calls
    ]


def test_every_item_is_listed_in_pages_of_1000() -> None:
    with respx.mock() as router:
        route = _serve_items(router, total=2500)
        items = toolbox.list_items(DATASET, "dev")

    assert [item["id"] for item in items] == [f"item-{n}" for n in range(2500)]
    assert _pages_requested(route) == [(1000, 0), (1000, 1000), (1000, 2000)]


def test_an_exact_multiple_of_the_page_reads_one_empty_page() -> None:
    with respx.mock() as router:
        route = _serve_items(router, total=2000)
        items = toolbox.list_items(DATASET, "dev")

    assert len(items) == 2000
    assert _pages_requested(route) == [(1000, 0), (1000, 1000), (1000, 2000)]


def test_a_limit_shrinks_the_last_page() -> None:
    with respx.mock() as router:
        route = _serve_items(router, total=5000)
        items = toolbox.list_items(DATASET, "dev", limit=1500)

    assert len(items) == 1500
    assert _pages_requested(route) == [(1000, 0), (500, 1000)]


def test_a_limit_below_a_page_is_one_request() -> None:
    with respx.mock() as router:
        route = _serve_items(router, total=5000)
        items = toolbox.list_items(DATASET, "dev", limit=10)

    assert len(items) == 10
    assert _pages_requested(route) == [(10, 0)]


def test_requests_carry_the_key_and_the_configured_timeout() -> None:
    with respx.mock() as router:
        route = _serve_items(router, total=3)
        toolbox.list_items(DATASET, "dev")

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer bench-key"
    assert set(request.extensions["timeout"].values()) == {120}


def test_toolbox_base_urls_comes_first(monkeypatch) -> None:
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{SECONDARY},{PRIMARY}")
    monkeypatch.setenv("TOOLBOX_BASE_URLS", f"{SECONDARY},{PRIMARY}")
    with respx.mock() as router:
        route = router.get(f"{SECONDARY}/v1/datasets/{DATASET}/splits/dev/items/x").mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        assert toolbox.get_item(DATASET, "dev", "x") == {"id": "x"}

    assert route.called


def test_item_and_artifact_reads() -> None:
    base = f"{PRIMARY}/v1/datasets/{DATASET}/splits/dev/items/x"
    with respx.mock() as router:
        router.get(base).mock(return_value=httpx.Response(200, json={"id": "x"}))
        router.get(f"{base}/artifacts/images/page 1.jpg").mock(
            return_value=httpx.Response(200, content=b"jpeg")
        )
        assert toolbox.get_item(DATASET, "dev", "x") == {"id": "x"}
        assert toolbox.get_artifact(DATASET, "dev", "x", "images/page 1.jpg") == b"jpeg"


def test_a_failed_listing_is_raised_typed_not_returned_empty() -> None:
    with respx.mock() as router:
        router.get(ITEMS).mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(ToolboxProviderUnavailable):
            toolbox.list_items(DATASET, "dev")


@pytest.mark.parametrize(
    ("provider", "expected"),
    [(None, provider_default("toolbox_provider")), ("mineru", "mineru")],
)
def test_extract_structure_uses_the_given_provider_or_the_configured_one(
    tmp_path, provider, expected
) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"png")
    with respx.mock() as router:
        route = router.post(EXTRACT).mock(
            return_value=httpx.Response(200, json={"status": "succeeded", "document": {}})
        )
        result = toolbox.extract_structure(image, provider)

    assert result["status"] == "succeeded"
    assert f'name="provider"\r\n\r\n{expected}'.encode() in route.calls.last.request.content


# The harness's configuration equals the core's for the clients it uses: the
# same environment gives the same endpoints, key, timeout, retries, backoff
# and provider. The core's side is a fresh Settings(), read from that same
# environment, so defaults are compared too.

TOOLBOX_VARIABLES = (
    "TOOLBOX_BASE_URL",
    "TOOLBOX_BASE_URLS",
    "TOOLBOX_API_KEY",
    "TOOLBOX_TIMEOUT_SECONDS",
    "TOOLBOX_RETRIES",
    "TOOLBOX_RETRY_BACKOFF_SECONDS",
    "TOOLBOX_PROVIDER",
)

ENVIRONMENTS = {
    "defaults": {},
    "single endpoint": {"TOOLBOX_BASE_URL": PRIMARY, "TOOLBOX_API_KEY": "k"},
    "endpoints list wins": {
        "TOOLBOX_BASE_URL": PRIMARY,
        "TOOLBOX_BASE_URLS": f" {SECONDARY}, {PRIMARY}/ ",
    },
    "budgets": {
        "TOOLBOX_TIMEOUT_SECONDS": "90",
        "TOOLBOX_RETRIES": "3",
        "TOOLBOX_RETRY_BACKOFF_SECONDS": "1.5",
    },
    "provider": {"TOOLBOX_PROVIDER": "mineru"},
    "empty provider": {"TOOLBOX_PROVIDER": ""},
}


def _shape(client) -> dict:
    return {
        "endpoints": client.endpoints,
        "provider": client.provider,
        "api_key": client.api_key,
        "timeout_seconds": client.timeout_seconds,
        "retries": client.retries,
        "retry_backoff_seconds": client.retry_backoff_seconds,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ENVIRONMENTS.values(), ids=ENVIRONMENTS.keys())
@pytest.mark.parametrize("client_cls", [ToolboxDatasetClient, ToolboxStructureClient])
async def test_the_harness_configures_clients_like_the_core(
    monkeypatch, environment, client_cls
) -> None:
    for variable in TOOLBOX_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    for variable, value in environment.items():
        monkeypatch.setenv(variable, value)
    monkeypatch.setattr(toolbox_client, "settings", Settings())

    core = toolbox_client.make_toolbox_client(client_cls)
    harness = make_client(client_cls, toolbox.client_config())
    try:
        assert _shape(harness) == _shape(core)
    finally:
        await core.close()
        await harness.close()


def test_a_failover_is_reported_on_stderr(capsys) -> None:
    toolbox.client_config().on_failover(ToolboxEndpoint(PRIMARY), ToolboxTimeout("slow"))

    assert f"Toolbox endpoint {PRIMARY} failed (ToolboxTimeout: slow)" in capsys.readouterr().err


BENCH_DIR = Path(__file__).resolve().parents[1] / "scripts" / "bench"


def test_the_harness_reaches_the_toolbox_without_the_core_s_toolbox_modules() -> None:
    """#402 acceptance: scripts/bench imports no backend.tools.toolbox_* module."""
    offenders = []
    for path in BENCH_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [alias.name for alias in node.names] if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            )
            offenders += [
                f"{path.name}: {name}" for name in names
                if name.startswith("backend.tools.toolbox_")
            ]
    assert offenders == []
