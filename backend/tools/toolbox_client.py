"""Core-side access to the Acessilia Toolbox.

The transport, the capability registry and the per-capability clients live in
the SDK (``libs/sdk``, package ``acessilia_sdk``). This module builds those
clients from the core's ``settings`` (:func:`make_toolbox_client`) and keeps
the names other modules import from here.
"""

from __future__ import annotations

from typing import Any, TypeVar

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
    ToolboxCapabilityClient,
    ToolboxEndpoint,
    ToolboxUnavailable,
    parse_endpoints,
)
from acessilia_sdk.toolbox.clients import (
    ToolboxDocxClient,
    ToolboxMathClient,
    ToolboxPdfUaClient,
)
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


def _log_failover(endpoint: ToolboxEndpoint, error: ToolboxError) -> None:
    logger.warning(
        "Toolbox endpoint {} failed ({}: {}); trying the next one",
        endpoint.base_url,
        type(error).__name__,
        error,
    )


def _class_defaults(client_cls: type[ToolboxCapabilityClient]) -> dict[str, Any]:
    """Settings that only some clients take."""
    if issubclass(client_cls, ToolboxMathClient):
        return {"transform_provider": settings.toolbox_math_provider}
    if issubclass(client_cls, ToolboxPdfUaClient):
        # The shared Toolbox timeout (default one hour) is far too long for
        # an export that renders in seconds.
        return {"timeout_seconds": settings.toolbox_pdf_ua_timeout_seconds}
    if issubclass(client_cls, ToolboxDocxClient):
        return {"timeout_seconds": settings.toolbox_docx_timeout_seconds}
    return {}


def make_toolbox_client(client_cls: type[ClientT], **overrides: Any) -> ClientT:
    """Build an SDK capability client configured from the core's ``settings``.

    The provider comes from the ``settings`` attribute named by the class's
    ``provider_key``, so ``TOOLBOX_*_PROVIDER`` overrides keep working;
    clients without a provider key (artifacts, datasets) get none.
    ``overrides`` win over settings; ``None`` values are ignored, and passing
    ``base_url`` replaces the configured endpoints.

    Every client retries timeouts and unavailable instances on the same
    endpoint, with backoff (``TOOLBOX_RETRIES``/``TOOLBOX_RETRY_BACKOFF_SECONDS``).
    """
    kwargs: dict[str, Any] = {
        "endpoints": toolbox_endpoints(),
        "provider": (
            getattr(settings, client_cls.provider_key) if client_cls.provider_key else None
        ),
        "timeout_seconds": settings.toolbox_timeout_seconds,
        "api_key": settings.toolbox_api_key,
        "on_failover": _log_failover,
        "retries": settings.toolbox_retries,
        "retry_backoff_seconds": settings.toolbox_retry_backoff_seconds,
        **_class_defaults(client_cls),
    }
    overrides = {key: value for key, value in overrides.items() if value is not None}
    if "base_url" in overrides:
        kwargs.pop("endpoints")
    kwargs.update(overrides)
    return client_cls(**kwargs)


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
    "toolbox_endpoints",
]
