"""Base class for the per-capability Toolbox clients."""

from __future__ import annotations

import asyncio
import random
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
from acessilia_sdk.toolbox.endpoints import (
    FAILOVER_ERRORS,
    ToolboxEndpoint,
    parse_endpoints,
)
from acessilia_sdk.toolbox.errors import (
    ToolboxArtifactNotFound,
    ToolboxError,
    ToolboxIncompatibleEndpoint,
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

#: Indirection so tests can observe the backoff without waiting.
_sleep = asyncio.sleep


class ToolboxCapabilityClient:
    """Holds the connections, auth headers and provider of one capability family.

    Configuration is passed in explicitly; the SDK reads no settings or
    environment. Subclasses set ``provider_key`` (a key of
    ``PROVIDER_DEFAULTS``) and only shape parameters and results around
    :meth:`_execute`.

    Pass ``base_url`` for one Toolbox, normally a load balancer in front of
    stateless replicas that share the artifact store: that is the primary way
    to stay available, and artifact ids stay valid across replicas. Pass
    ``endpoints`` (``ToolboxEndpoint`` objects, URLs, or a comma-separated
    string) only to reach *independent* Toolbox deployments, tried in order
    (see :mod:`acessilia_sdk.toolbox.endpoints`). A secondary endpoint is used
    only when its catalogue publishes the capability at the contract version
    this SDK expects, for the client's provider; ``catalog_refresh_seconds``
    and ``catalog_stale_seconds`` tune those secondary catalogues and have no
    effect with a single endpoint. When only one endpoint was tried, its own
    error is raised; ``ToolboxUnavailable`` is raised once two or more failed.

    ``retries`` re-sends a request to the same endpoint after a timeout or an
    unavailable instance, waiting ``retry_backoff_seconds * 2**attempt`` with
    jitter, before moving on. Enable it only for idempotent capabilities.

    ``resend_file_on_missing_artifact`` sends the file again when an endpoint
    does not know an ``artifact_id``. It only applies when the call passes
    **both** the ``artifact_id`` and the file (``file_path`` or ``upload``);
    calls that send one or the other are unaffected. It is off by default, so
    a missing artifact is reported instead of silently re-uploaded.

    ``self._client`` and ``self.base_url`` address the **primary** endpoint
    only. A capability whose result must be fetched afterwards (an artifact)
    must use :meth:`_execute_on` and fetch it through the HTTP client it
    returns, or it will read from the wrong instance after a failover.
    """

    #: Provider key whose default applies when no ``provider`` is given.
    provider_key: ClassVar[str]

    def __init__(
        self,
        *,
        base_url: str | None = None,
        endpoints: str | Sequence[str | ToolboxEndpoint] | None = None,
        provider: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        on_failover: FailoverHook | None = None,
        retries: int = 0,
        retry_backoff_seconds: float = 0.5,
        resend_file_on_missing_artifact: bool = False,
        catalog_refresh_seconds: float = 60.0,
        catalog_stale_seconds: float = 900.0,
    ) -> None:
        if (base_url is None) == (endpoints is None):
            raise ValueError("Pass exactly one of base_url or endpoints")
        if retries < 0:
            raise ValueError("retries must be zero or positive")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be zero or positive")
        self.endpoints = (
            (ToolboxEndpoint(base_url or "", api_key),)
            if endpoints is None
            else _normalize_endpoints(endpoints)
        )
        self.provider = provider or provider_default(self.provider_key)
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self.api_key = api_key or ""
        self.on_failover = on_failover
        self.retries = retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.resend_file_on_missing_artifact = resend_file_on_missing_artifact
        self._clients = [
            httpx.AsyncClient(
                base_url=endpoint.base_url,
                timeout=httpx.Timeout(self.timeout_seconds),
                headers=self._headers_for(endpoint),
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
        # The primary endpoint, kept for callers that address one instance.
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

        A capability that returns an artifact must download it through that
        client, not through ``self._client``.
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
            except (*FAILOVER_ERRORS, ToolboxIncompatibleEndpoint) as exc:
                self._record_failover(causes, endpoint, exc)
                continue
            return http, result
        raise _combined(causes)

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
            await _sleep(self._backoff(attempt))
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int) -> float:
        """Exponential delay with equal jitter, so retries do not move in lockstep."""
        delay = self.retry_backoff_seconds * 2**attempt
        return delay / 2 + random.uniform(0, delay / 2)

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
        """Health of the first endpoint that answers.

        Fails over like :meth:`_execute` and calls ``on_failover``, but never
        retries: a probe reports the current state instead of waiting it out.
        """
        causes: list[tuple[str, ToolboxError]] = []
        for endpoint, http in zip(self.endpoints, self._clients):
            try:
                return await _health(http, endpoint.base_url)
            except FAILOVER_ERRORS as exc:
                self._record_failover(causes, endpoint, exc)
        raise _combined(causes)

    async def close(self) -> None:
        """Libera as conexões HTTP."""
        for http in self._clients:
            await http.aclose()

    @property
    def _auth_headers(self) -> dict[str, str]:
        """Auth header of the primary endpoint."""
        return self._headers_for(self.endpoints[0])

    def _headers_for(self, endpoint: ToolboxEndpoint) -> dict[str, str]:
        return auth_headers(
            endpoint.api_key if endpoint.api_key is not None else self.api_key
        )

    def _record_failover(
        self,
        causes: list[tuple[str, ToolboxError]],
        endpoint: ToolboxEndpoint,
        exc: ToolboxError,
    ) -> None:
        causes.append((endpoint.base_url, exc))
        if self.on_failover is not None and len(self.endpoints) > 1:
            self.on_failover(endpoint, exc)


def _normalize_endpoints(
    endpoints: str | Sequence[str | ToolboxEndpoint],
) -> tuple[ToolboxEndpoint, ...]:
    if isinstance(endpoints, str):
        return parse_endpoints(endpoints)
    normalized: list[ToolboxEndpoint] = []
    for item in endpoints:
        if isinstance(item, ToolboxEndpoint):
            normalized.append(item)
        elif isinstance(item, str):
            normalized.append(ToolboxEndpoint(item))
        else:
            raise TypeError(
                f"Toolbox endpoints must be URLs or ToolboxEndpoint, got {item!r}"
            )
    if not normalized:
        raise ValueError("At least one Toolbox endpoint is required")
    return tuple(normalized)


def _combined(causes: list[tuple[str, ToolboxError]]) -> ToolboxError:
    """The only failure itself, or every cause once two or more endpoints failed."""
    if len(causes) == 1:
        return causes[0][1]
    return ToolboxUnavailable(causes)


async def _require_compatible(
    catalog: CatalogCache, capability_id: str, provider: str
) -> None:
    reasons = missing_requirements(
        await catalog.get(), [Requirement(capability_id, provider)]
    )
    if reasons:
        raise ToolboxIncompatibleEndpoint("; ".join(reasons))


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
