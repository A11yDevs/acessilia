"""The Toolbox VLM gateway, for clients that hold a chat with its vision model.

The gateway is not a capability: it relays OpenAI-compatible chats to a VLM
provider of the Toolbox under that provider's concurrency limit, so a client
never holds the model server's address or key (docs/adr/0012). Its two routes
live here so no caller builds them by hand:

- ``POST {base}/v1/vlm/chat/completions``, the chat itself; an OpenAI-compatible
  client takes :func:`vlm_gateway_base_url` and appends ``chat/completions``;
- ``GET {base}/v1/providers/{id}/health``, read by :func:`vlm_provider_healthy`.

The provider id travels as the chat's ``model``. Its default is
``ROUTE_PROVIDER_DEFAULTS["toolbox_vlm_provider"]``, which the core's contract
check verifies against the providers the Toolbox registers.
"""

from __future__ import annotations

import httpx

from acessilia_sdk.toolbox.endpoints import ToolboxEndpoint
from acessilia_sdk.toolbox.transport import auth_headers

VLM_GATEWAY_PATH = "/v1/vlm"


def vlm_gateway_base_url(endpoint: ToolboxEndpoint) -> str:
    """OpenAI-compatible base URL of the endpoint's VLM gateway."""
    return f"{endpoint.base_url}{VLM_GATEWAY_PATH}"


async def vlm_provider_healthy(
    endpoint: ToolboxEndpoint,
    provider: str,
    *,
    api_key: str | None = None,
    timeout_seconds: float,
) -> bool:
    """Whether the endpoint reports ``provider`` healthy.

    The Toolbox answers with its own probe of the model server, so this says
    whether a chat sent now can reach the model. Any failure (network, auth,
    an unknown provider, a body without ``healthy``) reads as not healthy.
    ``api_key`` applies when the endpoint has none of its own.
    """
    try:
        async with httpx.AsyncClient(
            base_url=endpoint.base_url,
            timeout=timeout_seconds,
            headers=auth_headers(endpoint.api_key or api_key),
        ) as http:
            response = await http.get(f"/v1/providers/{provider}/health")
            if response.status_code != 200:
                return False
            body = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    return isinstance(body, dict) and body.get("healthy") is True


__all__ = ["VLM_GATEWAY_PATH", "vlm_gateway_base_url", "vlm_provider_healthy"]
