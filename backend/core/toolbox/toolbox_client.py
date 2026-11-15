"""Core-side access to the Acessilia Toolbox.

The transport, the capability registry, the per-capability clients and the
client factory live in the SDK (``libs/sdk``, package ``acessilia_sdk``). This
module maps the core's ``settings`` onto the SDK's
:class:`~acessilia_sdk.toolbox.ToolboxClientConfig`
(:func:`toolbox_client_config`, constitution 3.2), states the endpoint rule
both the clients and the planning gate follow (:func:`endpoints_from`), and
keeps the names other modules import from here.
"""

from __future__ import annotations

import inspect
from typing import Any, TypeVar

from acessilia_sdk.toolbox import (
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnsupportedMediaType,
    auth_headers,
    execute_capability,
    require_capability,
)
from acessilia_sdk.toolbox import (
    PROVIDER_DEFAULTS,
    ToolboxCapabilityClient,
    ToolboxClientConfig,
    ToolboxEndpoint,
    ToolboxUnavailable,
    make_client,
    parse_endpoints,
)
from acessilia_sdk.toolbox import clients as _sdk_clients
from acessilia_sdk.toolbox.transport import media_type_for as _media_type
from backend.config.settings import settings
from backend.core.config import ToolboxConfig
from backend.core.logger import logger


ClientT = TypeVar("ClientT", bound=ToolboxCapabilityClient)


def endpoints_from(base_urls: str, base_url: str) -> tuple[ToolboxEndpoint, ...]:
    """The Toolbox endpoints, in the order they are tried.

    ``base_urls`` (``TOOLBOX_BASE_URLS``) lists independent deployments;
    without it, ``base_url`` (``TOOLBOX_BASE_URL``) is the only endpoint
    (docs/adr/0006). Raises ``ValueError`` for a URL the SDK cannot use.
    """
    return parse_endpoints(base_urls.strip() or base_url)


def toolbox_endpoints() -> tuple[ToolboxEndpoint, ...]:
    """The Toolbox endpoints configured for the capability clients (:func:`endpoints_from`)."""
    return endpoints_from(settings.toolbox_base_urls, settings.toolbox_base_url)


def toolbox_vlm_endpoint() -> ToolboxEndpoint:
    """The endpoint that receives the agents' VLM chats with ``AI_CLIENT=toolbox``.

    The first of :func:`toolbox_endpoints`: an Agno model takes one base URL,
    so these chats do not fail over (docs/adr/0012). The health route probes
    this same endpoint, so it reports what the agents will meet.
    """
    return toolbox_endpoints()[0]


def _log_failover(endpoint: ToolboxEndpoint, error: ToolboxError) -> None:
    logger.warning(
        "Toolbox endpoint {} failed ({}: {}); trying the next one",
        endpoint.base_url,
        type(error).__name__,
        error,
    )


#: The ``timeout_key`` of every SDK client that has its own timeout (the
#: exports): each names a ``settings`` attribute.
TIMEOUT_KEYS: frozenset[str] = frozenset(
    value.timeout_key
    for value in vars(_sdk_clients).values()
    if inspect.isclass(value)
    and issubclass(value, ToolboxCapabilityClient)
    and value.timeout_key
)


def toolbox_client_config() -> ToolboxClientConfig:
    """The SDK client configuration, read from the core's ``settings``.

    Read on every call, so a changed setting (or a test's monkeypatch) applies
    to the next client. Providers come from the ``TOOLBOX_*_PROVIDER``
    settings named by ``PROVIDER_DEFAULTS``, and export timeouts from the
    settings named by each client's ``timeout_key``.
    """
    return ToolboxClientConfig(
        endpoints=toolbox_endpoints(),
        api_key=settings.toolbox_api_key,
        timeout_seconds=settings.toolbox_timeout_seconds,
        retries=settings.toolbox_retries,
        retry_backoff_seconds=settings.toolbox_retry_backoff_seconds,
        providers={key: getattr(settings, key) for key in PROVIDER_DEFAULTS},
        timeouts={key: getattr(settings, key) for key in TIMEOUT_KEYS},
        on_failover=_log_failover,
    )


#: ``ToolboxConfig`` fields the Toolbox clients and handlers still read from
#: ``settings`` (ADR-0016, step 3, toolbox PRs 2 and 3). The planning gate
#: reads the run's config; a run whose config differs from the settings here
#: would be admitted by the gate for a deployment, key or provider its calls
#: do not use. Each toolbox PR removes the fields it moves, and the last one
#: removes this check.
TOOLBOX_FIELDS_STILL_IN_SETTINGS = (
    "base_url",
    "base_urls",
    "api_key",
    "timeout_seconds",
    "retries",
    "retry_backoff_seconds",
    "extraction_timeout_seconds",
    "providers",
    "timeouts",
    "use_remote_cache",
    "use_artifact_store",
    "media_inspect_enabled",
    "pdf_validate_enabled",
)


def refuse_toolbox_unlike_the_clients(toolbox: ToolboxConfig) -> None:
    """Refuse a run's ``toolbox`` that the clients, still on ``settings``, would not follow.

    Raises ``ValueError`` naming the fields that differ.
    """
    from backend.config.core_config import core_config_from_settings

    clients = core_config_from_settings().toolbox
    differ = [
        name
        for name in TOOLBOX_FIELDS_STILL_IN_SETTINGS
        if getattr(toolbox, name) != getattr(clients, name)
    ]
    if differ:
        raise ValueError(
            "The run's ToolboxConfig differs from the settings the Toolbox clients "
            f"still read, in {', '.join(differ)}; until ADR-0016's toolbox group is "
            "moved, pass these through the settings."
        )


def make_toolbox_client(client_cls: type[ClientT], **overrides: Any) -> ClientT:
    """Build an SDK capability client configured from the core's ``settings``.

    Delegates to :func:`acessilia_sdk.toolbox.make_client` with
    :func:`toolbox_client_config`. The provider comes from the ``settings``
    attribute named by the class's ``provider_key``, so ``TOOLBOX_*_PROVIDER``
    overrides keep working; clients without a provider key (artifacts,
    datasets) get none. ``overrides`` win over settings; ``None`` values are
    ignored, and passing ``base_url`` replaces the configured endpoints.

    Every client retries timeouts and unavailable instances on the same
    endpoint, with backoff (``TOOLBOX_RETRIES``/``TOOLBOX_RETRY_BACKOFF_SECONDS``),
    and fails over between ``TOOLBOX_BASE_URLS``, for idempotent capabilities
    only. The SDK decides per call from its registry (#406): a call to a
    non-idempotent capability (``dataset.sample``) gets one attempt.
    """
    return make_client(client_cls, toolbox_client_config(), **overrides)


__all__ = [
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
    "refuse_toolbox_unlike_the_clients",
    "require_capability",
    "toolbox_client_config",
    "toolbox_endpoints",
]
