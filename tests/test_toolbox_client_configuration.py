"""Specialized clients preserve transport settings and close their resources."""
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from backend.config.settings import settings
from backend.tools.toolbox_adjudicate_client import ToolboxAdjudicateClient
from backend.tools.toolbox_layout_client import ToolboxLayoutClient
from backend.tools.toolbox_media_inspect_client import ToolboxMediaInspectClient
from backend.tools.toolbox_orientation_client import ToolboxOrientationClient
from backend.tools.toolbox_page_ocr_client import ToolboxPageOcrClient


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_defaults", [True, False])
@pytest.mark.parametrize("client_type,provider_setting,method,capability,arguments", [
    (ToolboxLayoutClient, "toolbox_layout_provider", "analyze", "document.layout.analyze", {}),
    (ToolboxMediaInspectClient, "toolbox_media_inspect_provider", "inspect", "media.inspect", {}),
    (ToolboxOrientationClient, "toolbox_orientation_provider", "detect", "image.page.orient", {}),
    (ToolboxPageOcrClient, "toolbox_page_ocr_provider", "transcribe", "document.ocr.page", {}),
    (ToolboxAdjudicateClient, "toolbox_adjudicate_provider", "judge_page", "document.adjudicate.page",
     {"candidate_a": "First candidate", "candidate_b": "Second candidate"}),
])
async def test_request_configuration_and_close(
    monkeypatch, client_type, provider_setting, method, capability, arguments,
    configured_defaults,
):
    monkeypatch.setattr(settings, "toolbox_base_url", "http://configured-toolbox/")
    monkeypatch.setattr(settings, "toolbox_timeout_seconds", 21)
    monkeypatch.setattr(settings, "toolbox_api_key", "synthetic-test-key")
    monkeypatch.setattr(settings, provider_setting, "configured-provider")
    options = {} if configured_defaults else {
        "base_url": "http://override-toolbox/", "provider": "override-provider",
        "timeout_seconds": 13, "api_key": "",
    }
    base_url = "http://configured-toolbox" if configured_defaults else "http://override-toolbox"
    provider = "configured-provider" if configured_defaults else "override-provider"
    timeout = 21 if configured_defaults else 13
    client = client_type(**options)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{base_url}/v1/capabilities/{capability}:execute").mock(
            return_value=httpx.Response(200, json={"status": "succeeded", "document": {}}),
        )
        try:
            await getattr(client, method)(artifact_id="sha256:" + "a" * 64, **arguments)
            request = route.calls.last.request
            expected_auth = "Bearer synthetic-test-key" if configured_defaults else None
            assert request.headers.get("Authorization") == expected_auth
            assert parse_qs(request.content.decode())["provider"] == [provider]
            assert request.extensions["timeout"]["read"] == timeout
        finally:
            await client.close()
        assert client._client.is_closed
