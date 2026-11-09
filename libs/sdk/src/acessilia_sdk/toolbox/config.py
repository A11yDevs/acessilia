"""Explicit configuration for the capability clients, and a factory that uses it.

The SDK reads no settings and no environment (ADR-0002): a caller builds a
:class:`ToolboxClientConfig` from its own configuration source and passes it to
:func:`make_client`. The core maps its ``settings`` onto this object
(``backend/tools/toolbox_client.py``); a script or a benchmark harness can build
one by hand, with no core install.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypeVar

from acessilia_sdk.toolbox.client import (
    FailoverHook,
    ToolboxCapabilityClient,
    _normalize_endpoints,
)
from acessilia_sdk.toolbox.clients.math import ToolboxMathClient
from acessilia_sdk.toolbox.endpoints import ToolboxEndpoint

ClientT = TypeVar("ClientT", bound=ToolboxCapabilityClient)

#: The provider key of the math client's second provider (conversion and
#: verbalization), passed as ``transform_provider``.
MATH_TRANSFORM_PROVIDER_KEY = "toolbox_math_provider"


@dataclass(frozen=True)
class ToolboxClientConfig:
    """What a capability client needs, with every value explicit.

    ``endpoints`` lists one Toolbox (normally a load balancer) or several
    independent deployments, tried in order (ADR-0006). It accepts a
    comma-separated string of URLs, or a sequence of URLs and
    ``ToolboxEndpoint`` objects; after construction it is always a tuple of
    ``ToolboxEndpoint``. ``providers`` maps a client's
    ``provider_key`` (a key of ``PROVIDER_DEFAULTS``) to a provider id; a
    missing key leaves the SDK's default. ``timeouts`` maps a client's
    ``timeout_key`` to its own timeout; a missing key uses ``timeout_seconds``.
    ``on_failover`` is called when a call moves to the next endpoint.
    """

    endpoints: tuple[ToolboxEndpoint, ...] | str | Sequence[str | ToolboxEndpoint]
    api_key: str = ""
    timeout_seconds: float | None = None
    retries: int = 0
    retry_backoff_seconds: float = 0.5
    providers: Mapping[str, str] = field(default_factory=dict)
    timeouts: Mapping[str, float] = field(default_factory=dict)
    on_failover: FailoverHook | None = None

    def __post_init__(self) -> None:
        # The same parsing and validation the client applies to ``endpoints``.
        endpoints: str | Sequence[str | ToolboxEndpoint] = self.endpoints
        object.__setattr__(self, "endpoints", _normalize_endpoints(endpoints))
        # Read-only copies: one config can serve concurrent callers.
        object.__setattr__(self, "providers", MappingProxyType(dict(self.providers)))
        object.__setattr__(self, "timeouts", MappingProxyType(dict(self.timeouts)))


def _client_kwargs(
    client_cls: type[ToolboxCapabilityClient], config: ToolboxClientConfig
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "endpoints": config.endpoints,
        "provider": (
            config.providers.get(client_cls.provider_key) if client_cls.provider_key else None
        ),
        "timeout_seconds": config.timeout_seconds,
        "api_key": config.api_key,
        "on_failover": config.on_failover,
        "retries": config.retries,
        "retry_backoff_seconds": config.retry_backoff_seconds,
    }
    if issubclass(client_cls, ToolboxMathClient):
        kwargs["transform_provider"] = config.providers.get(MATH_TRANSFORM_PROVIDER_KEY)
    if client_cls.timeout_key:
        # Exports that render in seconds have their own timeout: the shared
        # one is far too long for them.
        kwargs["timeout_seconds"] = config.timeouts.get(
            client_cls.timeout_key, config.timeout_seconds
        )
    return kwargs


def make_client(
    client_cls: type[ClientT], config: ToolboxClientConfig, **overrides: Any
) -> ClientT:
    """Build ``client_cls`` from ``config``.

    ``overrides`` win over the configuration; ``None`` values are ignored, and
    passing ``base_url`` replaces the configured endpoints. The caller owns the
    client and closes it (``await client.close()``) in the loop that used it.
    """
    kwargs = _client_kwargs(client_cls, config)
    overrides = {key: value for key, value in overrides.items() if value is not None}
    if "base_url" in overrides:
        kwargs.pop("endpoints")
    kwargs.update(overrides)
    return client_cls(**kwargs)


__all__ = ["MATH_TRANSFORM_PROVIDER_KEY", "ToolboxClientConfig", "make_client"]
