"""VLM gateway routes: the chat base URL and the provider health probe."""

from __future__ import annotations

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import (
    ToolboxEndpoint,
    vlm_gateway_base_url,
    vlm_provider_healthy,
)

BASE_URL = "http://toolbox.test"
HEALTH_ROUTE = f"{BASE_URL}/v1/providers/qwen3-vl-8b/health"


def test_gateway_base_url_is_the_vlm_prefix_of_the_endpoint() -> None:
    assert vlm_gateway_base_url(ToolboxEndpoint(f"{BASE_URL}/")) == f"{BASE_URL}/v1/vlm"


@pytest.mark.asyncio
@respx.mock
async def test_endpoint_key_wins_over_the_client_key() -> None:
    route = respx.get(HEALTH_ROUTE).mock(
        return_value=httpx.Response(200, json={"healthy": True})
    )

    healthy = await vlm_provider_healthy(
        ToolboxEndpoint(BASE_URL, api_key="endpoint-key"),
        "qwen3-vl-8b",
        api_key="client-key",
        timeout_seconds=1,
    )

    assert healthy is True
    assert route.calls.last.request.headers["authorization"] == "Bearer endpoint-key"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"healthy": False}),
        httpx.Response(200, text="not json"),
        httpx.Response(404, json={"detail": "unknown provider"}),
        httpx.ConnectError("refused"),
    ],
)
async def test_any_failure_reads_as_not_healthy(response) -> None:
    route = respx.get(HEALTH_ROUTE)
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)

    healthy = await vlm_provider_healthy(
        ToolboxEndpoint(BASE_URL), "qwen3-vl-8b", timeout_seconds=1
    )

    assert healthy is False
