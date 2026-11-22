"""Core-side access to the Acessilia Toolbox.

The transport, the capability registry, the per-capability clients and the
client factory live in the SDK (``libs/sdk``, package ``acessilia_sdk``). This
module maps the run's :class:`~acessilia_core.config.ToolboxConfig` onto the
SDK's :class:`~acessilia_sdk.toolbox.ToolboxClientConfig`
(:func:`toolbox_client_config`, constitution 3.2; ADR-0016 step 3), states the endpoint rule
both the clients and the planning gate follow (:func:`endpoints_from`), and
keeps the names other modules import from here.
"""

from __future__ import annotations

import inspect
from typing import Any, TypeVar

from acessilia_core.config import ToolboxConfig
from acessilia_core.logger import logger
from acessilia_sdk.toolbox import (
    PROVIDER_DEFAULTS,
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityClient,
    ToolboxCapabilityError,
    ToolboxClientConfig,
    ToolboxContractViolation,
    ToolboxEndpoint,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnavailable,
    ToolboxUnsupportedMediaType,
    auth_headers,
    clients as _sdk_clients,
    execute_capability,
    make_client,
    parse_endpoints,
    require_capability,
)

ClientT = TypeVar("ClientT", bound=ToolboxCapabilityClient)


def endpoints_from(base_urls: str, base_url: str) -> tuple[ToolboxEndpoint, ...]:
    """The Toolbox endpoints, in the order they are tried.

    ``base_urls`` (``TOOLBOX_BASE_URLS``) lists independent deployments;
    without it, ``base_url`` (``TOOLBOX_BASE_URL``) is the only endpoint
    (docs/adr/0006). Raises ``ValueError`` for a URL the SDK cannot use.
    """
    return parse_endpoints(base_urls.strip() or base_url)


def toolbox_endpoints(toolbox: ToolboxConfig) -> tuple[ToolboxEndpoint, ...]:
    """The Toolbox endpoints of ``toolbox`` for the capability clients (:func:`endpoints_from`)."""
    return endpoints_from(toolbox.base_urls, toolbox.base_url)


def toolbox_vlm_endpoint(toolbox: ToolboxConfig) -> ToolboxEndpoint:
    """The endpoint that receives the agents' VLM chats with ``AI_CLIENT=toolbox``.

    The first of :func:`toolbox_endpoints`: an Agno model takes one base URL,
    so these chats do not fail over (docs/adr/0012). The health route probes
    this same endpoint, so it reports what the agents will meet.
    """
    return toolbox_endpoints(toolbox)[0]


def _log_failover(endpoint: ToolboxEndpoint, error: ToolboxError) -> None:
    logger.warning(
        "Toolbox endpoint {} failed ({}: {}); trying the next one",
        endpoint.base_url,
        type(error).__name__,
        error,
    )


#: The ``timeout_key`` of every SDK client that has its own timeout (the
#: exports): the keys of ``ToolboxConfig.timeouts``, each named after a setting.
TIMEOUT_KEYS: frozenset[str] = frozenset(
    value.timeout_key
    for value in vars(_sdk_clients).values()
    if inspect.isclass(value)
    and issubclass(value, ToolboxCapabilityClient)
    and value.timeout_key
)


def toolbox_client_config(toolbox: ToolboxConfig) -> ToolboxClientConfig:
    """The SDK client configuration of the run's ``toolbox``.

    Providers come from ``toolbox.providers``, keyed like
    ``PROVIDER_DEFAULTS``, and export timeouts from ``toolbox.timeouts``,
    keyed by each client's ``timeout_key``.
    """
    return ToolboxClientConfig(
        endpoints=toolbox_endpoints(toolbox),
        api_key=toolbox.api_key,
        timeout_seconds=toolbox.timeout_seconds,
        retries=toolbox.retries,
        retry_backoff_seconds=toolbox.retry_backoff_seconds,
        providers=dict(toolbox.providers),
        timeouts=dict(toolbox.timeouts),
        on_failover=_log_failover,
    )


def make_toolbox_client(
    client_cls: type[ClientT], toolbox: ToolboxConfig, **overrides: Any
) -> ClientT:
    """Build an SDK capability client configured from the run's ``toolbox``.

    Delegates to :func:`acessilia_sdk.toolbox.make_client` with
    :func:`toolbox_client_config`. The provider is the one ``toolbox.providers``
    names for the class's ``provider_key``; clients without a provider key
    (artifacts, datasets) get none. ``overrides`` win over the config;
    ``None`` values are ignored, and passing ``base_url`` replaces the
    configured endpoints.

    Every client retries timeouts and unavailable instances on the same
    endpoint, with backoff (``TOOLBOX_RETRIES``/``TOOLBOX_RETRY_BACKOFF_SECONDS``),
    and fails over between ``TOOLBOX_BASE_URLS``, for idempotent capabilities
    only. The SDK decides per call from its registry (#406): a call to a
    non-idempotent capability (``dataset.sample``) gets one attempt.
    """
    return make_client(client_cls, toolbox_client_config(toolbox), **overrides)


__all__ = [
    "PROVIDER_DEFAULTS",
    "TIMEOUT_KEYS",
    "ToolboxArtifactNotFound",
    "ToolboxAuthenticationError",
    "ToolboxCapabilityClient",
    "ToolboxCapabilityError",
    "ToolboxContractViolation",
    "ToolboxError",
    "ToolboxProviderUnavailable",
    "ToolboxTimeout",
    "ToolboxUnavailable",
    "ToolboxUnsupportedMediaType",
    "auth_headers",
    "endpoints_from",
    "execute_capability",
    "make_toolbox_client",
    "require_capability",
    "toolbox_client_config",
    "toolbox_endpoints",
]
