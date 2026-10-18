"""Base class for the per-capability Toolbox clients."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, ClassVar

import httpx

from acessilia_sdk.toolbox.capabilities import provider_default
from acessilia_sdk.toolbox.catalog import (
    CatalogCache,
    Requirement,
    fetch_catalog,
    missing_requirements,
)
from acessilia_sdk.toolbox.endpoints import FAILOVER_ERRORS, ToolboxEndpoint
from acessilia_sdk.toolbox.errors import (
    ToolboxArtifactNotFound,
    ToolboxCapabilityError,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnavailable,
)
from acessilia_sdk.toolbox.transport import (
    auth_headers,
    execute_capability,
    raise_for_error,
)

#: SDK-side fallback used only when the caller passes no ``timeout_seconds``.
#: The core always injects ``settings.toolbox_timeout_seconds``, so this value
#: does not need to track the core default.
DEFAULT_TIMEOUT_SECONDS = 3600

#: Called with the endpoint that failed and its error before the next one is
#: tried. The SDK has no logger; the caller decides what to record.
FailoverHook = Callable[[ToolboxEndpoint, ToolboxError], None]


class ToolboxCapabilityClient:
    """Holds the connections, auth headers and provider of one capability family.

    Configuration is passed in explicitly; the SDK reads no settings or
    environment. Subclasses set ``provider_key`` (a key of
    ``PROVIDER_DEFAULTS``) and only shape parameters and results around
    :meth:`_execute`.

    Pass ``base_url`` for one Toolbox, normally a load balancer in front of
    stateless replicas that share the artifact store: that is the primary way
    to stay available, and artifact ids stay valid across replicas. Pass
    ``endpoints`` only to reach *independent* Toolbox deployments, tried in
    order (see :mod:`acessilia_sdk.toolbox.endpoints`). A secondary endpoint
    is used only when its catalogue publishes the capability at the contract
    version this SDK expects, for the client's provider.

    ``retries`` re-sends a request to the same endpoint after a timeout or an
    unavailable instance, before moving on. Enable it only for idempotent
    capabilities. ``resend_file_on_missing_artifact`` sends the file again
    when an endpoint does not know an ``artifact_id``; it is off by default,
    so a missing artifact is reported instead of silently re-uploaded.
    """

    #: Provider key whose default applies when no ``provider`` is given.
    provider_key: ClassVar[str]

    def __init__(
        self,
        *,
        base_url: str | None = None,
        endpoints: Sequence[ToolboxEndpoint] | None = None,
        provider: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        on_failover: FailoverHook | None = None,
        retries: int = 0,
        resend_file_on_missing_artifact: bool = False,
        catalog_refresh_seconds: float = 60.0,
        catalog_stale_seconds: float = 900.0,
    ) -> None:
        if (base_url is None) == (endpoints is None):
            raise ValueError("Pass exactly one of base_url or endpoints")
        if endpoints is None:
            endpoints = (ToolboxEndpoint(base_url or "", api_key),)
        if not endpoints:
            raise ValueError("At least one Toolbox endpoint is required")
        if retries < 0:
            raise ValueError("retries must be zero or positive")
        self.endpoints = tuple(endpoints)
        self.provider = provider or provider_default(self.provider_key)
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self.api_key = api_key or ""
        self.on_failover = on_failover
        self.retries = retries
        self.resend_file_on_missing_artifact = resend_file_on_missing_artifact
        self._clients = [
            httpx.AsyncClient(
                base_url=endpoint.base_url,
                timeout=httpx.Timeout(self.timeout_seconds),
                headers=auth_headers(
                    endpoint.api_key if endpoint.api_key is not None else self.api_key
                ),
            )
            for endpoint in self.endpoints
        ]
        # Secondary endpoints are independent deployments: their catalogue is
        # checked before use. The primary one is checked by the caller's
        # availability gate, as before.
        self._catalogs: list[CatalogCache | None] = [None] + [
            CatalogCache(
                partial(fetch_catalog, http),
                refresh_seconds=catalog_refresh_seconds,
                stale_seconds=catalog_stale_seconds,
            )
            for http in self._clients[1:]
        ]
        # The first endpoint, kept for callers that address one instance.
        self.base_url = self.endpoints[0].base_url
        self._client = self._clients[0]

    async def _execute(
        self,
        capability_id: str,
        *,
        provider: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        _, result = await self._execute_on(capability_id, provider=provider, **kwargs)
        return result

    async def _execute_on(
        self,
        capability_id: str,
        *,
        provider: str | None = None,
        **kwargs: Any,
    ) -> tuple[httpx.AsyncClient, dict[str, Any]]:
        """Execute with failover; return the HTTP client of the endpoint that served it.

        A capability that returns an artifact must download it from that same
        endpoint.
        """
        provider = provider or self.provider
        causes: list[tuple[str, ToolboxError]] = []
        for endpoint, http, catalog in zip(self.endpoints, self._clients, self._catalogs):
            try:
                if catalog is not None:
                    await _require_compatible(catalog, capability_id, provider)
                result = await self._execute_with_retries(
                    http, capability_id, provider, kwargs
                )
            except (*FAILOVER_ERRORS, _IncompatibleEndpoint) as exc:
                causes.append((endpoint.base_url, exc))
                if self.on_failover is not None:
                    self.on_failover(endpoint, exc)
                continue
            return http, result
        if len(causes) == 1:
            raise causes[0][1]
        raise ToolboxUnavailable(causes)

    async def _execute_with_retries(
        self,
        http: httpx.AsyncClient,
        capability_id: str,
        provider: str,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            try:
                return await self._execute_once(http, capability_id, provider, kwargs)
            except FAILOVER_ERRORS:
                if attempt == self.retries:
                    raise
        raise AssertionError("unreachable")

    async def _execute_once(
        self,
        http: httpx.AsyncClient,
        capability_id: str,
        provider: str,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return await execute_capability(
                http, capability_id, provider=provider, **kwargs
            )
        except ToolboxArtifactNotFound:
            has_file = (
                kwargs.get("file_path") is not None or kwargs.get("upload") is not None
            )
            if (
                not self.resend_file_on_missing_artifact
                or not kwargs.get("artifact_id")
                or not has_file
            ):
                raise
        return await execute_capability(
            http,
            capability_id,
            provider=provider,
            **{**kwargs, "artifact_id": None},
        )

    async def health(self) -> dict[str, Any]:
        """Health of the first endpoint that answers."""
        causes: list[tuple[str, ToolboxError]] = []
        for endpoint, http in zip(self.endpoints, self._clients):
            try:
                return await _health(http, endpoint.base_url)
            except FAILOVER_ERRORS as exc:
                causes.append((endpoint.base_url, exc))
        if len(causes) == 1:
            raise causes[0][1]
        raise ToolboxUnavailable(causes)

    async def close(self) -> None:
        """Libera as conexões HTTP."""
        for http in self._clients:
            await http.aclose()

    @property
    def _auth_headers(self) -> dict[str, str]:
        return auth_headers(self.api_key)


class _IncompatibleEndpoint(ToolboxCapabilityError):
    """A secondary endpoint does not publish the capability as this SDK expects."""


async def _require_compatible(
    catalog: CatalogCache, capability_id: str, provider: str
) -> None:
    reasons = missing_requirements(
        await catalog.get(), [Requirement(capability_id, provider)]
    )
    if reasons:
        raise _IncompatibleEndpoint("; ".join(reasons))


async def _health(http: httpx.AsyncClient, base_url: str) -> dict[str, Any]:
    try:
        response = await http.get("/v1/health")
    except httpx.TimeoutException as e:
        raise ToolboxTimeout(f"Timeout ao verificar health da Toolbox: {e}") from e
    except httpx.RequestError as e:
        raise ToolboxProviderUnavailable(
            f"Toolbox indisponível em {base_url}: {e}"
        ) from e
    raise_for_error(response, "health")
    return response.json()


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "FailoverHook", "ToolboxCapabilityClient"]
