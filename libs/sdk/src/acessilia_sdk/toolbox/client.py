"""Base class for the per-capability Toolbox clients."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from acessilia_sdk.toolbox.capabilities import provider_default
from acessilia_sdk.toolbox.errors import ToolboxProviderUnavailable, ToolboxTimeout
from acessilia_sdk.toolbox.transport import (
    auth_headers,
    execute_capability,
    raise_for_error,
)

#: SDK-side fallback used only when the caller passes no ``timeout_seconds``.
#: The core always injects ``settings.toolbox_timeout_seconds``, so this value
#: does not need to track the core default.
DEFAULT_TIMEOUT_SECONDS = 3600


class ToolboxCapabilityClient:
    """Holds the connection, auth header and provider of one capability family.

    Configuration is passed in explicitly; the SDK reads no settings or
    environment. Subclasses set ``provider_key`` (a key of ``PROVIDER_DEFAULTS``)
    and only shape parameters and results around :meth:`_execute`.
    """

    #: Provider key whose default applies when no ``provider`` is given.
    provider_key: ClassVar[str]

    def __init__(
        self,
        *,
        base_url: str,
        provider: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.provider = provider or provider_default(self.provider_key)
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self.api_key = api_key or ""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds),
            headers=auth_headers(self.api_key),
        )

    async def _execute(
        self,
        capability_id: str,
        *,
        provider: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await execute_capability(
            self._client,
            capability_id,
            provider=provider or self.provider,
            **kwargs,
        )

    async def health(self) -> dict[str, Any]:
        """Verifica se a Toolbox está operacional."""
        try:
            response = await self._client.get("/v1/health")
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao verificar health da Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e
        raise_for_error(response, "health")
        return response.json()

    async def close(self) -> None:
        """Libera a conexão HTTP."""
        await self._client.aclose()

    @property
    def _auth_headers(self) -> dict[str, str]:
        return auth_headers(self.api_key)


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "ToolboxCapabilityClient"]
