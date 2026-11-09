"""Core-side access to the Acessilia Toolbox.

The transport, the capability registry, the per-capability clients and the
client factory live in the SDK (``libs/sdk``, package ``acessilia_sdk``). This
module only maps the core's ``settings`` onto the SDK's
:class:`~acessilia_sdk.toolbox.ToolboxClientConfig`
(:func:`toolbox_client_config`, constitution 3.2), and keeps the names other
modules import from here.
"""

from __future__ import annotations

import inspect
from typing import Any, TypeVar

# Re-exported only for callers the stage-1 branch of #381 moves (the
# orchestrator's handlers); new code imports acessilia_sdk.runtime directly.
# The re-export goes once stage 1 has landed (#402, step 2).
from acessilia_sdk.runtime import run_sync
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
from backend.tools.logger import logger


ClientT = TypeVar("ClientT", bound=ToolboxCapabilityClient)


def toolbox_endpoints() -> tuple[ToolboxEndpoint, ...]:
    """The Toolbox endpoints configured for the capability clients.

    ``TOOLBOX_BASE_URLS`` lists independent deployments, tried in order;
    without it, ``TOOLBOX_BASE_URL`` is the only endpoint (docs/adr/0006).
    """
    base_urls = settings.toolbox_base_urls.strip()
    return parse_endpoints(base_urls or settings.toolbox_base_url)


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
    "execute_capability",
    "make_toolbox_client",
    "require_capability",
    "run_sync",
    "toolbox_client_config",
    "toolbox_endpoints",
]
